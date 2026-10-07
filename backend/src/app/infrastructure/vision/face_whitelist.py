"""Who is it: known faces loaded once from reference photos, matched by face embedding.

Two small ONNX models run by OpenCV (no TensorFlow): YuNet finds and aligns the face, SFace turns
it into an embedding (a vector of 128 numbers). Two photos of the same person give close vectors.

Each person can have several photos: the file stem without its trailing number is the name shown
in the UI, e.g. `known_faces/kevan1.jpg` and `known_faces/kevan2.jpg` -> "kevan". A camera face is
compared to every photo and the closest one wins, so a few clear, front-facing shots per person
work best. Photos and camera crops go through the same pipeline, so their vectors are comparable.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"

# Cosine similarity at or above this is the same person (SFace's recommended threshold).
MATCH_THRESHOLD = 0.363
# YuNet's confidence that a face is there.
FACE_SCORE_THRESHOLD = 0.8
# Smaller faces carry too little detail to tell people apart.
MIN_FACE_SIZE = 40
# Distance between the eyes over the face width: ~0.5 for a frontal face, well under 0.35 in
# profile. Faces in profile get confused with each other, so they are not identified at all.
MIN_FRONTALITY = 0.35
# Phone photos are 4000px wide: downscale before detection, the face stays large enough.
_REFERENCE_MAX_SIDE = 1280
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


class FaceEncoder:
    """Largest usable face of an image -> embedding."""

    def __init__(self, models_dir: Path) -> None:
        self._detector = cv2.FaceDetectorYN.create(
            str(models_dir / DETECTOR_FILE), "", (320, 320), FACE_SCORE_THRESHOLD
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(models_dir / RECOGNIZER_FILE), "")

    def encode(self, bgr_image: np.ndarray) -> np.ndarray | None:
        """None when there is no face, or only one that is too small or in profile."""
        height, width = bgr_image.shape[:2]
        if min(height, width) < MIN_FACE_SIZE:
            return None
        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(bgr_image)
        if faces is None or len(faces) == 0:
            return None
        face = max(faces, key=lambda f: f[2] * f[3])
        if not is_usable_face(face):
            return None
        aligned = self._recognizer.alignCrop(bgr_image, face)
        return np.asarray(self._recognizer.feature(aligned), dtype=np.float32).flatten()


class FaceWhitelist:
    def __init__(self, known: dict[str, list[np.ndarray]]) -> None:
        self._known = known

    @property
    def size(self) -> int:
        """Number of known people (not photos)."""
        return len(self._known)

    @classmethod
    def load(cls, known_faces_dir: Path, encoder: FaceEncoder) -> FaceWhitelist:
        known: dict[str, list[np.ndarray]] = {}
        if not known_faces_dir.is_dir():
            logger.warning(
                "known faces directory %s does not exist; whitelist is empty", known_faces_dir
            )
            return cls(known)

        for path in sorted(known_faces_dir.iterdir()):
            if path.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            image = _read_reference(path)
            embedding = encoder.encode(image) if image is not None else None
            if embedding is None:
                logger.warning(
                    "no clear front-facing face in %s, skipping it as a reference", path.name
                )
                continue
            name = person_name(path.stem)
            known.setdefault(name, []).append(embedding)
            logger.info("loaded known face %r from %s", name, path.name)

        if not known:
            logger.warning(
                "no known faces loaded from %s; everyone will be an intruder", known_faces_dir
            )
        return cls(known)

    def match(self, face_embedding: np.ndarray) -> tuple[str, float] | None:
        """Best match for a face embedding, as (name, similarity), or None under the threshold."""
        best_name: str | None = None
        best_similarity = -1.0
        for name, embeddings in self._known.items():
            for known_embedding in embeddings:
                similarity = cosine_similarity(face_embedding, known_embedding)
                if similarity > best_similarity:
                    best_name, best_similarity = name, similarity
        if best_name is None or best_similarity < MATCH_THRESHOLD:
            return None
        return best_name, best_similarity


def person_name(stem: str) -> str:
    """`kevan`, `kevan2` and `kevan_2` all belong to "kevan"."""
    return re.sub(r"[\s_-]*\d+$", "", stem) or stem


def is_usable_face(face: np.ndarray) -> bool:
    """Large enough and facing the camera, from one YuNet row:
    x, y, w, h, right eye x/y, left eye x/y, nose x/y, mouth corners x/y, score."""
    width, height = float(face[2]), float(face[3])
    if min(width, height) < MIN_FACE_SIZE:
        return False
    right_eye_x, left_eye_x = float(face[4]), float(face[6])
    return abs(left_eye_x - right_eye_x) / width >= MIN_FRONTALITY


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _read_reference(path: Path) -> np.ndarray | None:
    image = cv2.imread(str(path))  # applies the EXIF orientation of phone photos
    if image is None:
        logger.warning("cannot read %s, skipping it as a reference", path.name)
        return None
    scale = _REFERENCE_MAX_SIDE / max(image.shape[:2])
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return image
