"""Matching logic (cosine similarity + threshold) and face filters, without loading the models."""

import cv2
import numpy as np
import pytest

from app.infrastructure.vision import face_whitelist as vision
from app.infrastructure.vision.face_whitelist import MATCH_THRESHOLD, FaceWhitelist

KEVAN = np.array([1.0, 0.0, 0.0])
ALICE = np.array([0.0, 1.0, 0.0])


@pytest.fixture
def whitelist() -> FaceWhitelist:
    return FaceWhitelist({"kevan": [KEVAN], "alice": [ALICE]})


def test_identical_embedding_matches(whitelist):
    match = whitelist.match(KEVAN.copy())
    assert match is not None
    name, similarity = match
    assert name == "kevan"
    assert similarity == pytest.approx(1.0)


def test_close_embedding_matches_the_nearest_known_face(whitelist):
    match = whitelist.match(np.array([0.95, 0.05, 0.0]))
    assert match is not None
    assert match[0] == "kevan"


def test_orthogonal_embedding_does_not_match(whitelist):
    assert whitelist.match(np.array([0.0, 0.0, 1.0])) is None


def test_empty_whitelist_never_matches():
    empty = FaceWhitelist({})
    assert empty.size == 0
    assert empty.match(KEVAN.copy()) is None


def test_similarity_just_under_the_threshold_is_rejected(whitelist):
    # Rotate away from kevan towards the axis nobody uses, so it does not drift towards alice.
    theta = np.arccos(MATCH_THRESHOLD) + 1e-3
    assert whitelist.match(np.array([np.cos(theta), 0.0, np.sin(theta)])) is None


def test_any_photo_of_a_person_can_match():
    kevan_side = np.array([0.0, 0.0, 1.0])
    whitelist = FaceWhitelist({"kevan": [KEVAN, kevan_side], "alice": [ALICE]})
    assert whitelist.size == 2
    match = whitelist.match(np.array([0.05, 0.0, 0.95]))
    assert match is not None
    assert match[0] == "kevan"


@pytest.mark.parametrize(
    ("stem", "name"),
    [("kevan", "kevan"), ("Kevan1", "Kevan"), ("kevan_2", "kevan"), ("kevan-12", "kevan")],
)
def test_photos_numbered_after_the_name_belong_to_the_same_person(stem, name):
    assert vision.person_name(stem) == name


def _face(width=100.0, height=120.0, eye_gap=50.0):
    """One YuNet row: x, y, w, h, right eye x/y, left eye x/y, nose, mouth corners, score."""
    centre = 50.0
    return np.array(
        [0, 0, width, height, centre - eye_gap / 2, 40, centre + eye_gap / 2, 40]
        + [50, 60, 35, 80, 65, 80, 0.95],
        dtype=np.float32,
    )


def test_frontal_face_is_usable():
    assert vision.is_usable_face(_face())


def test_profile_face_is_not_usable():
    assert not vision.is_usable_face(_face(eye_gap=15))


def test_tiny_face_is_not_usable():
    assert not vision.is_usable_face(_face(width=30, height=36, eye_gap=15))


def test_load_keeps_only_photos_with_a_usable_face(tmp_path):
    class Encoder:
        def encode(self, image):
            # The red photo has a face, the blue one does not.
            return KEVAN if image[0, 0, 2] > 0 else None

    red, blue = np.zeros((50, 50, 3), np.uint8), np.zeros((50, 50, 3), np.uint8)
    red[:, :, 2], blue[:, :, 0] = 255, 255
    cv2.imwrite(str(tmp_path / "kevan1.png"), red)
    cv2.imwrite(str(tmp_path / "kevan2.png"), blue)
    (tmp_path / "notes.txt").write_text("not a photo")

    whitelist = FaceWhitelist.load(tmp_path, Encoder())
    assert whitelist.size == 1
    assert whitelist.match(KEVAN.copy()) is not None
