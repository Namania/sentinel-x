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
    return FaceWhitelist({"kevan": KEVAN, "alice": ALICE})


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
    theta = np.arccos(1 - MATCH_THRESHOLD) + 1e-3
    borderline = np.array([np.cos(theta), np.sin(theta), 0.0])
    assert whitelist.match(borderline) is None
