"""YOLOv8n (COCO "person" class) for detection, with optional DeepFace/ArcFace identification.

Two separate models, two separate jobs:
  - YOLO finds *where* people are (fast, full-body boxes) - this is what has to stay under the
    ~100ms/frame budget from the brief. This alone is enough to answer "is anyone there?".
  - Optionally, for each person box, crop the top portion (roughly where the face is) and ask
    DeepFace for an embedding, then compare it to a FaceWhitelist to decide "known person" vs
    "intruder". This is the expensive, TensorFlow-backed half: skip it (whitelist=None) if all
    you need is presence detection, not identification - see VISION_IDENTIFY_FACES.

Both calls are synchronous/CPU-bound (ultralytics and deepface do not offer async APIs), so this
class is meant to be driven from a worker thread, not the asyncio event loop directly.

On the Pi (ARM64, CPU-only), plain PyTorch inference does not fit the 100ms budget - NCNN is
~2.8x faster there. Export once with `yolo_export_ncnn` (see that module) and this class will
pick up the exported model automatically; it falls back to the plain .pt (slower, but needs no
export step) when no NCNN export is found, which is convenient for local development.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
from ultralytics import YOLO

from app.domain.detection import BoundingBox, PersonDetection

if TYPE_CHECKING:
    from app.infrastructure.vision.face_whitelist import FaceWhitelist

logger = logging.getLogger(__name__)

_PERSON_CLASS_ID = 0  # COCO class 0 is "person"
_CONFIDENCE_THRESHOLD = 0.5


def _resolve_model_path(model_path: str) -> str:
    """Prefer an NCNN export (`<stem>_ncnn_model/`) next to the given .pt path, if one exists."""
    pt_path = Path(model_path)
    ncnn_dir = pt_path.with_name(f"{pt_path.stem}_ncnn_model")
    if ncnn_dir.is_dir():
        logger.info("using NCNN export %s", ncnn_dir)
        return str(ncnn_dir)
    logger.warning(
        "no NCNN export found at %s, falling back to %s (slower on ARM/CPU - see "
        "yolo_export_ncnn)",
        ncnn_dir,
        model_path,
    )
    return model_path


def load_person_model(model_path: str = "yolov8n.pt") -> YOLO:
    """Load YOLO and run one dummy inference.

    The first inference pulls in the rest of PyTorch's native stack (triton on x86). If
    TensorFlow (deepface) is already loaded at that point, the process segfaults - so this must
    run before the FaceWhitelist is loaded.
    """
    model = YOLO(_resolve_model_path(model_path))
    model.predict(np.zeros((64, 64, 3), dtype=np.uint8), verbose=False)
    return model


class YoloFaceAnalyzer:
    """Person detection, with optional face identification.

    Pass `whitelist=None` to skip identification entirely: every detected person comes back with
    `identity=None` (reported as an intruder), and `deepface` is never imported - no TensorFlow,
    no embedding computation, just YOLO.
    """

    def __init__(self, model: YOLO, whitelist: FaceWhitelist | None) -> None:
        self._whitelist = whitelist
        self._model = model

    def analyze(self, jpeg_frame: bytes) -> list[PersonDetection]:
        image = _decode_jpeg(jpeg_frame)
        if image is None:
            return []

        results = self._model.predict(
            image, classes=[_PERSON_CLASS_ID], conf=_CONFIDENCE_THRESHOLD, verbose=False
        )
        people: list[PersonDetection] = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])
            confidence = float(box.conf[0])
            identity, identity_confidence = self._identify(image, x1, y1, x2, y2)
            people.append(
                PersonDetection(
                    box=BoundingBox(x=x1, y=y1, width=x2 - x1, height=y2 - y1),
                    confidence=confidence,
                    identity=identity,
                    identity_confidence=identity_confidence,
                )
            )
        return people

    def _identify(
        self, image: np.ndarray, x1: int, y1: int, x2: int, y2: int
    ) -> tuple[str | None, float | None]:
        if self._whitelist is None or self._whitelist.size == 0:
            return None, None
        # The whole person box: the face detector inside embed_face finds the face itself.
        crop = image[max(y1, 0) : y2, max(x1, 0) : x2]
        if crop.size == 0:
            return None, None
        try:
            # Imported lazily: deepface (and the TensorFlow it requires) is only loaded when
            # identification is actually enabled.
            from app.infrastructure.vision.face_whitelist import embed_face

            embedding = embed_face(crop)
        except Exception:  # noqa: BLE001 - a bad crop must not kill the detection loop
            logger.debug("face embedding failed for a crop", exc_info=True)
            return None, None
        if embedding is None:  # no usable face: turned away, in profile or too small
            return None, None
        match = self._whitelist.match(embedding)
        if match is None:
            return None, None
        name, distance = match
        return name, 1.0 - distance


def _decode_jpeg(jpeg_frame: bytes) -> np.ndarray | None:
    buffer = np.frombuffer(jpeg_frame, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        logger.warning("could not decode a camera frame as JPEG")
    return image
