from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domain.alert import Alert, Direction, Metric


def _iso_z(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class AlertOutput:
    id: UUID
    device_id: str
    metric: Metric
    direction: Direction
    threshold: float
    opened_at: datetime
    opened_value: float
    peak_value: float
    resolved_at: datetime | None
    resolved_value: float | None

    @classmethod
    def from_entity(cls, alert: Alert) -> AlertOutput:
        return cls(**{f: getattr(alert, f) for f in cls.__dataclass_fields__})

    def to_event(self) -> dict[str, Any]:
        """JSON-safe payload, same shape as the REST response."""
        data = asdict(self)
        data["id"] = str(self.id)
        data["opened_at"] = _iso_z(self.opened_at)
        data["resolved_at"] = _iso_z(self.resolved_at)
        return data
