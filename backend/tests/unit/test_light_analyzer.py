"""The light pipeline's decisions (motion skip, when faces are checked), with fake models."""

import cv2
import numpy as np

from app.infrastructure.vision.face_whitelist import FaceWhitelist
from app.infrastructure.vision.light_analyzer import (
    RECHECK_KNOWN_SECONDS,
    RECHECK_UNKNOWN_SECONDS,
    LightVisionAnalyzer,
)
from app.infrastructure.vision.motion import MAX_SKIP_SECONDS, MotionGate
from app.infrastructure.vision.person_detector import DetectedPerson

KEVAN = np.array([1.0, 0.0, 0.0], dtype=np.float32)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeDetector:
    def __init__(self, box=(10, 10, 40, 80)) -> None:
        self.box = box
        self.calls = 0

    def detect(self, image):
        self.calls += 1
        return [DetectedPerson(box=self.box, confidence=0.9)] if self.box else []


class FakeEncoder:
    def __init__(self, embedding=KEVAN) -> None:
        self.embedding = embedding
        self.calls = 0

    def encode(self, image):
        self.calls += 1
        return self.embedding


def _jpeg(value: int) -> bytes:
    ok, encoded = cv2.imencode(".jpg", np.full((120, 160, 3), value, np.uint8))
    assert ok
    return encoded.tobytes()


def _analyzer(detector=None, encoder=None):
    clock = Clock()
    encoder = encoder or FakeEncoder()
    whitelist = FaceWhitelist({"kevan": [KEVAN]})
    analyzer = LightVisionAnalyzer(detector or FakeDetector(), (encoder, whitelist), clock)
    return analyzer, clock, encoder


def test_a_known_face_is_named():
    analyzer, _, _ = _analyzer()
    [person] = analyzer.analyze(_jpeg(50))
    assert person.identity == "kevan"
    assert person.box.width == 40


def test_nothing_runs_when_the_scene_did_not_change():
    detector = FakeDetector()
    analyzer, clock, _ = _analyzer(detector)
    first = analyzer.analyze(_jpeg(50))
    clock.now += 1
    assert analyzer.analyze(_jpeg(50)) is first
    assert detector.calls == 1


def test_a_change_in_the_scene_runs_the_detector_again():
    detector = FakeDetector()
    analyzer, clock, _ = _analyzer(detector)
    analyzer.analyze(_jpeg(50))
    clock.now += 1
    analyzer.analyze(_jpeg(200))
    assert detector.calls == 2


def test_a_still_scene_is_analysed_again_after_a_while():
    detector = FakeDetector()
    analyzer, clock, _ = _analyzer(detector)
    analyzer.analyze(_jpeg(50))
    clock.now += MAX_SKIP_SECONDS + 0.1
    analyzer.analyze(_jpeg(50))
    assert detector.calls == 2


def test_a_known_person_is_not_recognised_again_on_every_frame():
    analyzer, clock, encoder = _analyzer()
    for value in (50, 200, 50, 200):  # moving: the detector runs every time
        analyzer.analyze(_jpeg(value))
        clock.now += 1
    assert encoder.calls == 1

    clock.now += RECHECK_KNOWN_SECONDS
    analyzer.analyze(_jpeg(50))
    assert encoder.calls == 2


def test_an_unknown_person_is_retried_soon():
    stranger = FakeEncoder(np.array([0.0, 1.0, 0.0], dtype=np.float32))
    analyzer, clock, _ = _analyzer(encoder=stranger)
    [person] = analyzer.analyze(_jpeg(50))
    assert person.identity is None
    clock.now += RECHECK_UNKNOWN_SECONDS
    analyzer.analyze(_jpeg(200))
    assert stranger.calls == 2


def test_a_known_person_turning_away_keeps_their_name():
    encoder = FakeEncoder()
    analyzer, clock, _ = _analyzer(encoder=encoder)
    analyzer.analyze(_jpeg(50))
    encoder.embedding = None  # no readable face any more
    clock.now += RECHECK_KNOWN_SECONDS
    [person] = analyzer.analyze(_jpeg(200))
    assert person.identity == "kevan"


def test_without_face_identification_everyone_is_unnamed():
    analyzer = LightVisionAnalyzer(FakeDetector(), None, Clock())
    [person] = analyzer.analyze(_jpeg(50))
    assert person.identity is None


def test_an_undecodable_frame_returns_the_last_result():
    analyzer, _, _ = _analyzer()
    assert analyzer.analyze(b"not a jpeg") == []


def test_motion_gate_ignores_sensor_noise():
    gate = MotionGate()
    rng = np.random.default_rng(0)
    base = np.full((120, 160, 3), 100, np.uint8)
    assert not gate.is_still(base, 0.0)
    noisy = np.clip(base + rng.integers(-4, 5, base.shape), 0, 255).astype(np.uint8)
    assert gate.is_still(noisy, 1.0)
