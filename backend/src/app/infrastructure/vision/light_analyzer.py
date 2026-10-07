"""Light vision pipeline for the Raspberry Pi: OpenCV only, no PyTorch, no TensorFlow.

For each frame the worker hands over:
  1. nothing moved since the last analysis -> return the previous result, no model runs;
  2. YOLO finds the people (320px input);
  3. the tracker follows each person from the previous analysis;
  4. a face is recognised only for a new or unknown person, or to re-check a known one now and
     then - not for everyone on every frame.

Synchronous and CPU-bound: the worker runs it in a thread, one frame at a time.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import cv2
import numpy as np

from app.domain.detection import BoundingBox, PersonDetection
from app.infrastructure.vision.face_whitelist import FaceEncoder, FaceList
from app.infrastructure.vision.motion import MotionGate
from app.infrastructure.vision.person_detector import PersonDetector
from app.infrastructure.vision.tracker import PersonTracker, Track

# An unrecognised person (face turned away, too far) is tried again this often.
RECHECK_UNKNOWN_SECONDS = 1.0
# A recognised person is checked again this often, in case the tracker swapped two people.
RECHECK_KNOWN_SECONDS = 10.0


class LightVisionAnalyzer:
    def __init__(
        self,
        detector: PersonDetector,
        faces: tuple[FaceEncoder, FaceList] | None = None,
        blacklist: tuple[FaceEncoder, FaceList] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._detector = detector
        self._faces = faces if faces is not None and faces[1].size > 0 else None
        self._blacklist = blacklist if blacklist is not None and blacklist[1].size > 0 else None
        self._clock = clock
        self._tracker = PersonTracker()
        self._motion = MotionGate()
        self._last: list[PersonDetection] | None = None

    def analyze(self, jpeg_frame: bytes) -> list[PersonDetection]:
        image = cv2.imdecode(np.frombuffer(jpeg_frame, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return self._last or []
        now = self._clock()
        # Always asked, so the first frame becomes the motion reference.
        if self._motion.is_still(image, now) and self._last is not None:
            return self._last

        people = self._detector.detect(image)
        tracks = self._tracker.update([person.box for person in people])
        result = []
        for person, track in zip(people, tracks, strict=True):
            if self._needs_check(track, now):
                self._identify(image, track, now)
            x, y, width, height = person.box
            result.append(
                PersonDetection(
                    box=BoundingBox(x=x, y=y, width=width, height=height),
                    confidence=person.confidence,
                    identity=track.identity,
                    identity_confidence=track.identity_confidence,
                    blacklisted_as=track.blacklisted_as,
                    blacklist_confidence=track.blacklist_confidence,
                )
            )
        self._last = result
        return result

    @property
    def _encoder(self) -> FaceEncoder | None:
        faces = self._faces or self._blacklist
        return faces[0] if faces is not None else None

    def _needs_check(self, track: Track, now: float) -> bool:
        if self._encoder is None:
            return False
        # A blacklisted person is always rechecked at the unknown cadence: never relax watching
        # for them just because the tracker has kept their box for a while.
        wait = (
            RECHECK_KNOWN_SECONDS
            if track.identity and not track.blacklisted_as
            else RECHECK_UNKNOWN_SECONDS
        )
        return now - track.last_check >= wait

    def _identify(self, image: np.ndarray, track: Track, now: float) -> None:
        encoder = self._encoder
        assert encoder is not None
        track.last_check = now
        x, y, width, height = track.box
        embedding = encoder.encode(image[y : y + height, x : x + width])
        if embedding is None:
            # No readable face (turned away, in profile): a known person keeps their status.
            return
        if self._blacklist is not None:
            blacklist_match = self._blacklist[1].match(embedding)
            track.blacklisted_as, track.blacklist_confidence = (
                blacklist_match if blacklist_match else (None, None)
            )
        whitelist = self._faces[1] if self._faces is not None else None
        match = whitelist.match(embedding) if whitelist is not None else None
        track.identity, track.identity_confidence = match if match else (None, None)
