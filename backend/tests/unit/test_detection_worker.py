import asyncio
from collections.abc import AsyncIterator

import pytest

from app.domain.detection import BoundingBox, PersonDetection
from app.infrastructure.vision.detection_worker import DetectionWorker
from tests.unit.fakes import RecordingBroadcaster


class FakeAnalyzer:
    """Scriptable VisionAnalyzer: returns the next queued result for each call."""

    def __init__(self) -> None:
        self.calls: list[bytes] = []
        self._results: list[list[PersonDetection]] = []

    def queue(self, people: list[PersonDetection]) -> None:
        self._results.append(people)

    def analyze(self, jpeg_frame: bytes) -> list[PersonDetection]:
        self.calls.append(jpeg_frame)
        return self._results.pop(0) if self._results else []


class FailingAnalyzer:
    def analyze(self, jpeg_frame: bytes) -> list[PersonDetection]:
        raise RuntimeError("model exploded")


async def frames_from(items: list[bytes]) -> AsyncIterator[bytes]:
    for item in items:
        yield item


KNOWN_PERSON = PersonDetection(
    box=BoundingBox(x=1, y=2, width=3, height=4),
    confidence=0.9,
    identity="kevan",
    identity_confidence=0.8,
)
INTRUDER = PersonDetection(
    box=BoundingBox(x=5, y=6, width=7, height=8), confidence=0.7, identity=None
)


async def test_broadcasts_a_snapshot_for_each_analyzed_frame():
    analyzer = FakeAnalyzer()
    analyzer.queue([KNOWN_PERSON])
    broadcaster = RecordingBroadcaster()
    worker = DetectionWorker(frames_from([b"frame-a"]), analyzer, broadcaster, interval_seconds=0)

    await worker.run()

    assert len(broadcaster.broadcasts) == 1
    event = broadcaster.broadcasts[0]
    assert event["type"] == "vision.detection"
    assert event["data"]["has_intruder"] is False
    assert event["data"]["people"] == [
        {
            "box": {"x": 1, "y": 2, "width": 3, "height": 4},
            "confidence": 0.9,
            "identity": "kevan",
            "identity_confidence": 0.8,
            "is_intruder": False,
        }
    ]


async def test_has_intruder_true_when_any_person_is_unrecognised():
    analyzer = FakeAnalyzer()
    analyzer.queue([KNOWN_PERSON, INTRUDER])
    broadcaster = RecordingBroadcaster()
    worker = DetectionWorker(frames_from([b"frame-a"]), analyzer, broadcaster, interval_seconds=0)

    await worker.run()

    assert broadcaster.broadcasts[0]["data"]["has_intruder"] is True


async def test_throttles_analysis_to_the_configured_interval():
    analyzer = FakeAnalyzer()
    broadcaster = RecordingBroadcaster()
    # A long interval: only the first of several frames should actually be analyzed.
    worker = DetectionWorker(
        frames_from([b"a", b"b", b"c"]), analyzer, broadcaster, interval_seconds=60.0
    )

    await worker.run()

    assert analyzer.calls == [b"a"]
    assert len(broadcaster.broadcasts) == 1


async def test_keeps_the_latest_snapshot_available():
    analyzer = FakeAnalyzer()
    analyzer.queue([KNOWN_PERSON])
    worker = DetectionWorker(
        frames_from([b"frame-a"]), analyzer, RecordingBroadcaster(), interval_seconds=0
    )

    assert worker.latest is None
    await worker.run()
    assert worker.latest is not None
    assert worker.latest.people == (KNOWN_PERSON,)


async def test_a_failed_analysis_does_not_stop_the_worker():
    broadcaster = RecordingBroadcaster()
    worker = DetectionWorker(
        frames_from([b"a", b"b"]), FailingAnalyzer(), broadcaster, interval_seconds=0
    )

    await worker.run()

    assert broadcaster.broadcasts == []
    assert worker.latest is None


async def test_runs_analysis_in_a_worker_thread_without_blocking_the_event_loop():
    analyzer = FakeAnalyzer()
    analyzer.queue([KNOWN_PERSON])
    ticked = asyncio.Event()

    async def tick_soon():
        await asyncio.sleep(0)
        ticked.set()

    worker = DetectionWorker(
        frames_from([b"frame-a"]), analyzer, RecordingBroadcaster(), interval_seconds=0
    )
    await asyncio.gather(worker.run(), tick_soon())
    assert ticked.is_set()
