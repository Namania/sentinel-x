from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domain.sensor_reading import DeviceSummary, ReadingBucket, SensorReading


@dataclass(frozen=True, slots=True)
class ReadingInput:
    device_id: str
    recorded_at: datetime | None
    temperature_c: float | None
    humidity_pct: float | None
    gas_level: int | None
    gas_alert: bool


@dataclass(frozen=True, slots=True)
class ReadingOutput:
    id: UUID
    device_id: str
    recorded_at: datetime
    temperature_c: float | None
    humidity_pct: float | None
    gas_level: int | None
    gas_alert: bool

    @classmethod
    def from_entity(cls, reading: SensorReading) -> ReadingOutput:
        return cls(
            id=reading.id,
            device_id=reading.device_id,
            recorded_at=reading.recorded_at,
            temperature_c=reading.temperature_c,
            humidity_pct=reading.humidity_pct,
            gas_level=reading.gas_level,
            gas_alert=reading.gas_alert,
        )

    def to_event(self) -> dict[str, Any]:
        """JSON-safe payload for the WebSocket event."""
        data = asdict(self)
        data["id"] = str(self.id)
        # Same shape as the REST responses ("…Z"), whatever the source timezone.
        data["recorded_at"] = self.recorded_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return data


@dataclass(frozen=True, slots=True)
class BucketOutput:
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

    @classmethod
    def from_bucket(cls, bucket: ReadingBucket) -> BucketOutput:
        return cls(**asdict(bucket))


@dataclass(frozen=True, slots=True)
class DeviceOutput:
    device_id: str
    last_seen: datetime

    @classmethod
    def from_summary(cls, summary: DeviceSummary) -> DeviceOutput:
        return cls(device_id=summary.device_id, last_seen=summary.last_seen)
