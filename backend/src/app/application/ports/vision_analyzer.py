from typing import Protocol

from app.domain.detection import PersonDetection


class VisionAnalyzer(Protocol):
    """Finds people in a JPEG frame and matches each one against the known-faces whitelist."""

    def analyze(self, jpeg_frame: bytes) -> list[PersonDetection]: ...
