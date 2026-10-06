"""Health of the machine hosting the API: one sample every few seconds, kept in memory."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

EVENT_TYPE = "server.health"
DEFAULT_MAXLEN = 360  # 30 min at one sample every 5 s


@dataclass(frozen=True, slots=True)
class ServerHealth:
    recorded_at: datetime
    cpu_pct: float | None  # None on the first sample (no delta yet)
    mem_total_bytes: int
    mem_used_bytes: int
    disk_total_bytes: int
    disk_used_bytes: int
    temperature_c: float | None  # None when the host exposes no thermal zone
    load_1: float
    load_5: float
    load_15: float
    uptime_s: int


def to_dict(sample: ServerHealth) -> dict[str, Any]:
    """JSON-safe payload, same shape as the REST response."""
    data = asdict(sample)
    data["recorded_at"] = sample.recorded_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return data


def to_event(sample: ServerHealth) -> dict[str, Any]:
    return {"type": EVENT_TYPE, "data": to_dict(sample)}


class HealthHistory:
    """Ring buffer of the most recent samples, oldest first."""

    def __init__(self, maxlen: int = DEFAULT_MAXLEN) -> None:
        self._points: deque[ServerHealth] = deque(maxlen=maxlen)

    def append(self, sample: ServerHealth) -> None:
        self._points.append(sample)

    def latest(self) -> ServerHealth | None:
        return self._points[-1] if self._points else None

    def points(self) -> list[ServerHealth]:
        return list(self._points)

    def __len__(self) -> int:
        return len(self._points)
