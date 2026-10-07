"""The siren: should the buzzer sound, given the open alerts, the triggers and a mute?"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from app.domain.alert import METRICS, Alert, Direction, Metric

# "intruder" is not in METRICS (it has no threshold, see domain/alert.py) but can still trigger
# the siren: it comes first, an intruder outranks any sensor reason.
TRIGGERABLE_METRICS: tuple[Metric, ...] = (*METRICS, "intruder")
REASON_ORDER: tuple[Metric, ...] = ("intruder", "gas", "temperature", "humidity")
DIRECTIONS = ("low", "high")


@dataclass(frozen=True, slots=True)
class Trigger:
    metric: Metric
    direction: Direction | None  # None → both directions

    def matches(self, alert: Alert) -> bool:
        return alert.metric == self.metric and self.direction in (None, alert.direction)


def parse_triggers(spec: str) -> tuple[Trigger, ...]:
    """`"gas,temperature:high"` → triggers; an unknown metric or direction is a ValueError."""
    triggers: list[Trigger] = []
    for raw in spec.split(","):
        token = raw.strip()
        if not token:
            continue
        metric, _, direction = token.partition(":")
        if metric not in TRIGGERABLE_METRICS:
            raise ValueError(f"unknown metric in BUZZER_TRIGGERS: {token!r}")
        if direction and direction not in DIRECTIONS:
            raise ValueError(f"unknown direction in BUZZER_TRIGGERS: {token!r}")
        triggers.append(
            Trigger(cast(Metric, metric), cast(Direction, direction) if direction else None)
        )
    return tuple(triggers)


@dataclass(frozen=True, slots=True)
class SirenState:
    on: bool
    reason: Metric | None
    open: int
    muted_until: datetime | None


def decide(
    open_alerts: Sequence[Alert],
    triggers: Sequence[Trigger],
    muted_until: datetime | None,
    now: datetime,
) -> SirenState:
    """`on` when an open alert matches a trigger and no mute runs; `reason` survives a mute."""
    matching = [a for a in open_alerts if any(t.matches(a) for t in triggers)]
    reason = min((a.metric for a in matching), key=REASON_ORDER.index, default=None)
    mute_active = muted_until is not None and muted_until > now
    return SirenState(
        on=bool(matching) and not mute_active,
        reason=reason,
        open=len(open_alerts),
        muted_until=muted_until if mute_active else None,
    )
