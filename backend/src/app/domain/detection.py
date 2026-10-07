from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Pixel coordinates in the analysed frame (top-left origin)."""

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class PersonDetection:
    """One person found by YOLO, optionally matched against the face whitelist/blacklist."""

    box: BoundingBox
    confidence: float
    identity: str | None  # whitelisted person's name, or None if unrecognised
    identity_confidence: float | None = None
    blacklisted_as: str | None = None  # blacklisted person's name, or None if not a match
    blacklist_confidence: float | None = None

    @property
    def is_intruder(self) -> bool:
        return self.identity is None

    @property
    def is_blacklisted(self) -> bool:
        return self.blacklisted_as is not None


@dataclass(frozen=True, slots=True)
class DetectionSnapshot:
    """Result of one analysed frame, broadcast to viewers."""

    people: tuple[PersonDetection, ...]
    analyzed_at: datetime

    @property
    def has_intruder(self) -> bool:
        return any(person.is_intruder for person in self.people)

    @property
    def has_blacklisted(self) -> bool:
        return any(person.is_blacklisted for person in self.people)

    @classmethod
    def now(cls, people: tuple[PersonDetection, ...]) -> DetectionSnapshot:
        return cls(people=people, analyzed_at=datetime.now(UTC))
