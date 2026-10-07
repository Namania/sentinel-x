"""Background worker: pulls frames from the camera relay, runs vision analysis, broadcasts hits.

It is just another consumer of `CameraRelay.frames()` - the same fan-out the HTTP viewers use -
so it does not open a second connection to the camera. The models are synchronous and
CPU-bound, so each analysis runs in a worker thread (`asyncio.to_thread`) to avoid blocking the
event loop; the throttle keeps a slow Raspberry Pi from falling behind the live video.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.ports.vision_analyzer import VisionAnalyzer
from app.domain.detection import DetectionSnapshot, PersonDetection

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 1.0


class DetectionWorker:
    def __init__(
        self,
        frames: AsyncIterator[bytes],
        analyzer: VisionAnalyzer,
        broadcaster: EventBroadcaster,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._frames = frames
        self._analyzer = analyzer
        self._broadcaster = broadcaster
        self._interval_seconds = interval_seconds
        self._latest: DetectionSnapshot | None = None

    @property
    def latest(self) -> DetectionSnapshot | None:
        return self._latest

    async def run(self) -> None:
        last_run = 0.0
        async for frame in self._frames:
            now = time.monotonic()
            if now - last_run < self._interval_seconds:
                continue
            last_run = now
            await self._analyze(frame)

    async def _analyze(self, frame: bytes) -> None:
        try:
            people = await asyncio.to_thread(self._analyzer.analyze, frame)
        except Exception:  # noqa: BLE001 - one bad frame must not stop the worker
            logger.exception("vision analysis failed on a frame")
            return
        snapshot = DetectionSnapshot.now(tuple(people))
        self._latest = snapshot
        await self._broadcaster.broadcast(_to_event(snapshot))


def _to_event(snapshot: DetectionSnapshot) -> dict:
    return {
        "type": "vision.detection",
        "data": {
            "analyzed_at": snapshot.analyzed_at.isoformat(),
            "has_intruder": snapshot.has_intruder,
            "people": [_person_to_dict(person) for person in snapshot.people],
        },
    }


def _person_to_dict(person: PersonDetection) -> dict:
    return {
        "box": {
            "x": person.box.x,
            "y": person.box.y,
            "width": person.box.width,
            "height": person.box.height,
        },
        "confidence": person.confidence,
        "identity": person.identity,
        "identity_confidence": person.identity_confidence,
        "is_intruder": person.is_intruder,
    }
