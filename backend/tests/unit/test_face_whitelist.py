"""Tests the matching logic (cosine distance + threshold) without loading real DeepFace models.

Needs the backend's "vision" extra (deepface, numpy) - skipped otherwise, e.g. in the default CI
job, which intentionally does not install it (see pyproject.toml's vision extra).
"""

import pytest

np = pytest.importorskip("numpy")
vision = pytest.importorskip("app.infrastructure.vision.face_whitelist")
MATCH_THRESHOLD = vision.MATCH_THRESHOLD
FaceWhitelist = vision.FaceWhitelist

KEVAN = np.array([1.0, 0.0, 0.0])
ALICE = np.array([0.0, 1.0, 0.0])


@pytest.fixture
def whitelist() -> FaceWhitelist:
    return FaceWhitelist({"kevan": [KEVAN], "alice": [ALICE]})


def test_identical_embedding_matches(whitelist):
    match = whitelist.match(KEVAN.copy())
    assert match is not None
    name, distance = match
    assert name == "kevan"
    assert distance == pytest.approx(0.0, abs=1e-9)


def test_close_embedding_matches_the_nearest_known_face(whitelist):
    close_to_kevan = np.array([0.95, 0.05, 0.0])
    match = whitelist.match(close_to_kevan)
    assert match is not None
    assert match[0] == "kevan"


def test_orthogonal_embedding_does_not_match(whitelist):
    stranger = np.array([0.0, 0.0, 1.0])
    assert whitelist.match(stranger) is None


def test_empty_whitelist_never_matches():
    empty = FaceWhitelist({})
    assert empty.size == 0
    assert empty.match(KEVAN.copy()) is None


def test_distance_exactly_at_threshold_is_rejected(whitelist):
    # cosine distance 1 - cos(theta); pick an angle that lands just over the threshold.
    # Rotate away from kevan towards the axis nobody uses, so it does not drift towards alice.
    theta = np.arccos(1 - MATCH_THRESHOLD) + 1e-3
    borderline = np.array([np.cos(theta), 0.0, np.sin(theta)])
    assert whitelist.match(borderline) is None


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


def _area(width=100, height=120, eye_gap=50):
    return {
        "w": width,
        "h": height,
        "left_eye": (50 + eye_gap // 2, 40),
        "right_eye": (50 - eye_gap // 2, 40),
    }


def test_frontal_face_is_usable():
    assert vision.is_usable_face(_area())


def test_profile_face_is_not_usable():
    assert not vision.is_usable_face(_area(eye_gap=15))


def test_tiny_face_is_not_usable():
    assert not vision.is_usable_face(_area(width=30, height=36, eye_gap=15))


def test_face_without_eye_landmarks_is_not_usable():
    assert not vision.is_usable_face({"w": 100, "h": 120, "left_eye": None, "right_eye": None})
