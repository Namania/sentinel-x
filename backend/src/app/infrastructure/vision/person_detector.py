"""People in a frame: YOLOv8n exported to ONNX, run by OpenCV's DNN module.

No PyTorch at runtime: the model is converted to ONNX once, when the Docker image is built (see
the Dockerfile's `models` stage), and the same file runs on a PC and on the Raspberry Pi.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MODEL_FILE = "yolov8n.onnx"
# Must match the export size (Dockerfile). 320 instead of YOLO's usual 640 is ~4x less work and
# still enough to spot a person in a room.
INPUT_SIZE = 320
# People cut by the frame edge or close to a wide-angle webcam often score 0.35-0.5; below 0.35,
# false hits (a sleeve, furniture) start to show up.
CONFIDENCE_THRESHOLD = 0.35
# Two boxes overlapping more than this are the same person.
NMS_IOU_THRESHOLD = 0.45
_PERSON_CLASS_ID = 0  # COCO class 0 is "person"
_PAD_VALUE = 114  # grey padding, as during YOLO training


@dataclass(frozen=True, slots=True)
class DetectedPerson:
    """A person box in source-frame pixels: (x, y, width, height)."""

    box: tuple[int, int, int, int]
    confidence: float


@dataclass(frozen=True, slots=True)
class Letterbox:
    """How a frame was fitted into the square model input: scaled, then centred with padding."""

    scale: float
    pad_x: float
    pad_y: float


class PersonDetector:
    def __init__(self, models_dir: Path) -> None:
        self._net = cv2.dnn.readNetFromONNX(str(models_dir / MODEL_FILE))

    def detect(self, image: np.ndarray) -> list[DetectedPerson]:
        square, letterbox = letterbox_image(image, INPUT_SIZE)
        blob = cv2.dnn.blobFromImage(square, 1 / 255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True)
        self._net.setInput(blob)
        output = self._net.forward()
        height, width = image.shape[:2]
        return parse_output(output, letterbox, width, height)


def letterbox_image(image: np.ndarray, size: int) -> tuple[np.ndarray, Letterbox]:
    """Scale the frame to fit a `size` square without distortion, padding the rest."""
    height, width = image.shape[:2]
    scale = min(size / width, size / height)
    new_width, new_height = round(width * scale), round(height * scale)
    resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
    pad_x, pad_y = (size - new_width) / 2, (size - new_height) / 2
    left, top = int(pad_x), int(pad_y)
    square = cv2.copyMakeBorder(
        resized,
        top,
        size - new_height - top,
        left,
        size - new_width - left,
        cv2.BORDER_CONSTANT,
        value=(_PAD_VALUE, _PAD_VALUE, _PAD_VALUE),
    )
    return square, Letterbox(scale=scale, pad_x=left, pad_y=top)


def parse_output(
    output: np.ndarray, letterbox: Letterbox, frame_width: int, frame_height: int
) -> list[DetectedPerson]:
    """YOLOv8 output (1, 84, N): per candidate, centre x/y, width, height, then 80 class scores."""
    predictions = output[0].T  # (N, 84)
    scores = predictions[:, 4 + _PERSON_CLASS_ID]
    keep = scores >= CONFIDENCE_THRESHOLD
    if not np.any(keep):
        return []
    centres_sizes, scores = predictions[keep, :4], scores[keep]

    boxes = []
    for cx, cy, w, h in centres_sizes:
        x = (cx - w / 2 - letterbox.pad_x) / letterbox.scale
        y = (cy - h / 2 - letterbox.pad_y) / letterbox.scale
        boxes.append(
            _clip(x, y, w / letterbox.scale, h / letterbox.scale, frame_width, frame_height)
        )

    kept = cv2.dnn.NMSBoxes(boxes, scores.tolist(), CONFIDENCE_THRESHOLD, NMS_IOU_THRESHOLD)
    return [
        DetectedPerson(box=boxes[i], confidence=float(scores[i])) for i in np.array(kept).flatten()
    ]


def _clip(
    x: float, y: float, w: float, h: float, frame_width: int, frame_height: int
) -> tuple[int, int, int, int]:
    left, top = max(0, int(x)), max(0, int(y))
    right, bottom = min(frame_width, int(x + w)), min(frame_height, int(y + h))
    return left, top, max(0, right - left), max(0, bottom - top)
