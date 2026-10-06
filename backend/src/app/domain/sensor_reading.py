from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.errors import InvalidReading

DEVICE_ID_PATTERN = re.compile(r"^[a-z0-9-]{1,64}$")
TEMPERATURE_RANGE = (-40.0, 125.0)
HUMIDITY_RANGE = (0.0, 100.0)


def _check_range(name: str, value: float | None, bounds: tuple[float, float]) -> None:
    if value is None:
        return
    low, high = bounds
    if not low <= value <= high:
        raise InvalidReading(f"{name} must be between {low:g} and {high:g}")


def to_utc(moment: datetime) -> datetime:
    """Aware UTC datetime; a naive value is taken as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SensorReading:
    """One message from a device: the metrics it carried at one instant."""

    id: UUID
    device_id: str
    recorded_at: datetime
    temperature_c: float | None
    humidity_pct: float | None
    gas_level: int | None
    gas_alert: bool

    @classmethod
    def create(
        cls,
        *,
        device_id: str,
        recorded_at: datetime,
        temperature_c: float | None,
        humidity_pct: float | None,
        gas_level: int | None,
        gas_alert: bool,
    ) -> SensorReading:
        if not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise InvalidReading("device_id must match [a-z0-9-]{1,64}")
        _check_range("temperature_c", temperature_c, TEMPERATURE_RANGE)
        _check_range("humidity_pct", humidity_pct, HUMIDITY_RANGE)
        if gas_level is not None and gas_level < 0:
            raise InvalidReading("gas_level must be positive")
        return cls(
            id=uuid4(),
            device_id=device_id,
            recorded_at=to_utc(recorded_at),
            temperature_c=temperature_c,
            humidity_pct=humidity_pct,
            gas_level=gas_level,
            gas_alert=gas_alert,
        )


@dataclass(frozen=True, slots=True)
class ReadingBucket:
    """Aggregate of the readings of one device over one time bucket."""

    bucket_start: datetime
    count: int
    temperature_avg: float | None
    temperature_min: float | None
    temperature_max: float | None
    humidity_avg: float | None
    humidity_min: float | None
    humidity_max: float | None
    gas_avg: float | None
    gas_min: int | None
    gas_max: int | None
    gas_alerts: int


@dataclass(frozen=True, slots=True)
class DeviceSummary:
    device_id: str
    last_seen: datetime
