"""Whitelist of known faces, loaded once from reference photos and matched by embedding distance.

Each person can have several photos: the file stem without its trailing number is the name shown
in the UI, e.g. `known_faces/kevan1.jpg` and `known_faces/kevan2.jpg` -> "kevan". A camera face
is compared to every photo and the closest one wins, so a few clear, front-facing shots per
person work best.

Reference photos and camera crops go through the same pipeline (YuNet face detection + alignment,
then ArcFace), otherwise their embeddings are not comparable.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import cv2
import numpy as np
from deepface import DeepFace

logger = logging.getLogger(__name__)

# ArcFace embeddings: cosine distance below this is considered the same person.
# DeepFace's own recommended threshold for ArcFace is ~0.68; we go slightly stricter.
MATCH_THRESHOLD = 0.6

_MODEL_NAME = "ArcFace"
# Fast enough to run on every person box (detection + ArcFace ~120ms per face on a laptop CPU,
# ~1.2s with RetinaFace) and accurate enough to align the face for ArcFace.
_DETECTOR = "yunet"
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
# Smaller faces carry too little detail for ArcFace to tell people apart.
MIN_FACE_SIZE = 40
# Distance between the eyes over the face width: ~0.5 for a frontal face, well under 0.35 in
# profile. ArcFace confuses people in profile, so those faces are not identified at all.
MIN_FRONTALITY = 0.35
# Phone photos are 4000px wide: downscale before detection, the face stays large enough.
_REFERENCE_MAX_SIDE = 1280


class FaceWhitelist:
    def __init__(self, known: dict[str, list[np.ndarray]]) -> None:
        self._known = known

    @property
    def size(self) -> int:
        """Number of known people (not photos)."""
        return len(self._known)

    @classmethod
    def load(cls, known_faces_dir: Path) -> FaceWhitelist:
        known: dict[str, list[np.ndarray]] = {}
        if not known_faces_dir.is_dir():
            logger.warning(
                "known faces directory %s does not exist; whitelist is empty", known_faces_dir
            )
            return cls(known)

        for path in sorted(known_faces_dir.iterdir()):
            if path.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            try:
                embedding = _embed_reference(path)
            except Exception:  # noqa: BLE001 - a bad reference photo must not crash startup
                logger.exception("could not compute embedding for %s, skipping", path)
                continue
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
        """Best match for a face embedding, as (name, distance), or None above the threshold."""
        best_name: str | None = None
        best_distance = float("inf")
        for name, embeddings in self._known.items():
            for known_embedding in embeddings:
                distance = _cosine_distance(face_embedding, known_embedding)
                if distance < best_distance:
                    best_name, best_distance = name, distance
        if best_name is None or best_distance > MATCH_THRESHOLD:
            return None
        return best_name, best_distance


def person_name(stem: str) -> str:
    """`kevan`, `kevan2` and `kevan_2` all belong to "kevan"."""
    return re.sub(r"[\s_-]*\d+$", "", stem) or stem


def embed_face(bgr_image: np.ndarray) -> np.ndarray | None:
    """Embedding of the largest usable face in the image (a YOLO person crop or a photo).

    None when there is no face, or only one that is too small or in profile.
    """
    faces = DeepFace.represent(
        bgr_image,
        model_name=_MODEL_NAME,
        detector_backend=_DETECTOR,
        enforce_detection=False,  # no face is a normal outcome (person turned away)
        align=True,
    )
    # With enforce_detection=False, "no face found" comes back as the whole image, confidence 0.
    detected = [face for face in faces if face.get("face_confidence", 0) > 0]
    if not detected:
        return None
    face = max(detected, key=lambda f: f["facial_area"]["w"] * f["facial_area"]["h"])
    if not is_usable_face(face["facial_area"]):
        return None
    return np.asarray(face["embedding"], dtype=np.float64)


def is_usable_face(area: dict) -> bool:
    """Large enough and facing the camera, from DeepFace's `facial_area`."""
    width = area["w"]
    if min(width, area["h"]) < MIN_FACE_SIZE:
        return False
    left_eye, right_eye = area.get("left_eye"), area.get("right_eye")
    if not left_eye or not right_eye:
        return False
    return abs(left_eye[0] - right_eye[0]) / width >= MIN_FRONTALITY


def _embed_reference(path: Path) -> np.ndarray | None:
    image = cv2.imread(str(path))  # applies the EXIF orientation of phone photos
    if image is None:
        raise ValueError(f"cannot read {path}")
    scale = _REFERENCE_MAX_SIDE / max(image.shape[:2])
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return embed_face(image)


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 1.0
    return float(1.0 - np.dot(a, b) / denom)
