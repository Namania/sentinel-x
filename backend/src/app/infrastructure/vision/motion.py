"""Skips the analysis when nothing moved: comparing two tiny greyscale frames costs ~nothing,
running YOLO costs tens of milliseconds on the Raspberry Pi."""

from __future__ import annotations

import cv2
import numpy as np

# Frames are compared at this size: enough to see someone move, too small to see sensor noise.
_SIZE = (64, 48)
# Mean pixel difference (0-255) above which the scene changed. Webcam noise stays around 1.
CHANGE_THRESHOLD = 3.0
# Analyse anyway after this long, so a slow change (light, someone very still) is caught.
MAX_SKIP_SECONDS = 5.0


class MotionGate:
    def __init__(self) -> None:
        self._reference: np.ndarray | None = None
        self._last_analysis = 0.0

    def is_still(self, image: np.ndarray, now: float) -> bool:
        """True when the frame barely differs from the last analysed one (skip the analysis)."""
        small = cv2.GaussianBlur(
            cv2.cvtColor(
                cv2.resize(image, _SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY
            ),
            (5, 5),
            0,
        )
        if (
            self._reference is not None
            and now - self._last_analysis < MAX_SKIP_SECONDS
            and float(np.mean(cv2.absdiff(small, self._reference))) < CHANGE_THRESHOLD
        ):
            return True
        # Compared against the last *analysed* frame, so a slow drift adds up and is not missed.
        self._reference = small
        self._last_analysis = now
        return False
