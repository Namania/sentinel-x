"""Opens and resolves "intruder" alerts for blacklisted faces seen on camera.

One open alert per blacklisted person (`device_id` is `face:<name>`, distinct from sensor device
ids), the same open/resolve shape as a sensor alert: `RecordReading._apply_alerts` opens on a
threshold crossing, this opens on a face appearing; both close themselves when the condition
clears. `threshold`/`opened_value`/`peak_value` carry the match confidence (0-1), the closest
numeric equivalent a bounds-shaped `Alert` has for "how sure the camera is".
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.application.alerts.dtos import AlertOutput
from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.alert import Alert

logger = logging.getLogger(__name__)

DEVICE_PREFIX = "face:"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TrackBlacklistAlerts:
    """Reconciles open "intruder" alerts with who was last seen, once per analysed frame.

    Tracks which blacklisted names currently have an open alert in memory, so a frame with no one
    blacklisted costs no database round trip."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        broadcaster: EventBroadcaster,
        on_alerts_changed: Callable[[], Awaitable[None]] | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._uow_factory = uow_factory
        self._broadcaster = broadcaster
        self._on_alerts_changed = on_alerts_changed
        self._clock = clock
        self._open: dict[str, Alert] = {}

    async def sync(self, seen: frozenset[str], confidence: dict[str, float]) -> None:
        """`seen`: blacklisted names visible in the latest frame. Opens an alert for a new one,
        resolves the alert for one no longer seen; already-open alerts for people still seen are
        left untouched (no spam while someone stands in front of the camera)."""
        newly_seen = seen - self._open.keys()
        newly_gone = self._open.keys() - seen
        if not newly_seen and not newly_gone:
            return

        now = self._clock()
        events: list[tuple[str, Alert]] = []
        async with self._uow_factory() as uow:
            for name in newly_seen:
                opened = Alert.open(
                    device_id=f"{DEVICE_PREFIX}{name}",
                    metric="intruder",
                    direction="high",
                    threshold=0.0,
                    at=now,
                    value=confidence.get(name, 1.0),
                )
                await uow.alerts.add(opened)
                self._open[name] = opened
                events.append(("alert.opened", opened))
            for name in newly_gone:
                resolved = self._open.pop(name).resolve(at=now, value=0.0)
                await uow.alerts.save(resolved)
                events.append(("alert.resolved", resolved))
            await uow.commit()

        for kind, alert in events:
            await self._broadcaster.broadcast(
                {"type": kind, "data": AlertOutput.from_entity(alert).to_event()}
            )
        if self._on_alerts_changed is not None:
            try:
                await self._on_alerts_changed()
            except Exception:  # noqa: BLE001 - alerts are stored; the siren catches up later
                logger.exception("alert change hook failed")
