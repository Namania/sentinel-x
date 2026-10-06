"""Whitelist of known faces, loaded once from reference photos and matched by embedding distance.

Each file in `known_faces_dir` is one person: the file stem (without extension) is the name
shown in the UI, e.g. `known_faces/kevan.jpg` -> "kevan". One photo per person is enough; a
clear, front-facing shot works best.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from deepface import DeepFace

logger = logging.getLogger(__name__)

# ArcFace embeddings: cosine distance below this is considered the same person.
# DeepFace's own recommended threshold for ArcFace is ~0.68; we go slightly stricter.
MATCH_THRESHOLD = 0.6

_MODEL_NAME = "ArcFace"
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


class FaceWhitelist:
    def __init__(self, known: dict[str, np.ndarray]) -> None:
        self._known = known

    @property
    def size(self) -> int:
        return len(self._known)

    @classmethod
    def load(cls, known_faces_dir: Path) -> FaceWhitelist:
        known: dict[str, np.ndarray] = {}
        if not known_faces_dir.is_dir():
            logger.warning("known faces directory %s does not exist; whitelist is empty",
                            known_faces_dir)
            return cls(known)

        for path in sorted(known_faces_dir.iterdir()):
            if path.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            try:
                embedding = _embed(str(path))
            except Exception:  # noqa: BLE001 - a bad reference photo must not crash startup
                logger.exception("could not compute embedding for %s, skipping", path)
                continue
            known[path.stem] = embedding
            logger.info("loaded known face %r from %s", path.stem, path.name)

        if not known:
            logger.warning("no known faces loaded from %s; everyone will be an intruder",
                            known_faces_dir)
        return cls(known)

    def match(self, face_embedding: np.ndarray) -> tuple[str, float] | None:
        """Best match for a face embedding, as (name, distance), or None above the threshold."""
        best_name: str | None = None
        best_distance = float("inf")
        for name, known_embedding in self._known.items():
            distance = _cosine_distance(face_embedding, known_embedding)
            if distance < best_distance:
                best_name, best_distance = name, distance
        if best_name is None or best_distance > MATCH_THRESHOLD:
            return None
        return best_name, best_distance


def embed_face(bgr_crop: np.ndarray) -> np.ndarray:
    """Embedding for an already-cropped face (a YOLO person crop or similar)."""
    result = DeepFace.represent(
        bgr_crop,
        model_name=_MODEL_NAME,
        enforce_detection=False,  # the crop may be a loose box, not a tight DeepFace-style face
        detector_backend="skip",
    )
    return np.asarray(result[0]["embedding"], dtype=np.float64)


def _embed(image_path: str) -> np.ndarray:
    result = DeepFace.represent(image_path, model_name=_MODEL_NAME, detector_backend="retinaface")
    return np.asarray(result[0]["embedding"], dtype=np.float64)


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 1.0
    return float(1.0 - np.dot(a, b) / denom)
