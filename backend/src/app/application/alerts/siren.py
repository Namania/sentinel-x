"""The siren service: recompute the buzzer state after alert changes, publish it, mute it."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.siren import SirenState, Trigger, decide

logger = logging.getLogger(__name__)

EVENT_TYPE = "siren.state"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_z(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def siren_to_dict(state: SirenState, at: datetime) -> dict[str, Any]:
    """The MQTT payload and the WebSocket event body: `on` first, dates as `…Z`."""
    data = asdict(state)
    data["muted_until"] = _iso_z(state.muted_until)
    data["at"] = _iso_z(at)
    return data


class SirenPublisher(Protocol):
    async def publish(self, state: SirenState, at: datetime) -> None: ...


class Siren:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        publisher: SirenPublisher | None,
        broadcaster: EventBroadcaster,
        triggers: Sequence[Trigger],
        mute_minutes: int,
        clock: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._broadcaster = broadcaster
        self._triggers = tuple(triggers)
        self._mute = timedelta(minutes=mute_minutes)
        self._clock = clock
        self._sleep = sleep
        self._state = SirenState(on=False, reason=None, open=0, muted_until=None)
        self._muted_until: datetime | None = None
        self._announced = False
        # The last state the broker acknowledged; None until a publish succeeds, so a transition
        # that failed to publish is retried at the next refresh even if nothing changed.
        self._published: SirenState | None = None
        self._lock = asyncio.Lock()
        self._wake_up: asyncio.Task[None] | None = None

    @property
    def state(self) -> SirenState:
        return self._state

    async def refresh(self) -> SirenState:
        """Re-read the open alerts; publish and broadcast when the state changed, at start, or
        when the broker still lacks the current state. Serialised: concurrent callers (ingestion,
        the route, the wake-up) must not publish an older state after a newer one."""
        async with self._lock:
            now = self._clock()
            async with self._uow_factory() as uow:
                open_alerts = await uow.alerts.list("open", None, 500)
            new = decide(open_alerts, self._triggers, self._muted_until, now)
            self._state = new
            if not self._announced or new != self._published:
                await self._announce(new, now)
            return new

    async def mute(self, by: UUID) -> SirenState:
        self._muted_until = self._clock() + self._mute
        logger.info("siren muted until %s by %s", self._muted_until.isoformat(), by)
        self._schedule_wake_up(self._mute.total_seconds())
        return await self.refresh()

    async def unmute(self, by: UUID) -> SirenState:
        self._muted_until = None
        logger.info("siren unmuted by %s", by)
        self._cancel_wake_up()
        return await self.refresh()

    def close(self) -> None:
        self._cancel_wake_up()

    async def _announce(self, state: SirenState, at: datetime) -> None:
        self._announced = True
        if self._publisher is not None:
            try:
                await self._publisher.publish(state, at)
                self._published = state
            except Exception:  # noqa: BLE001 - the state is still served; the next refresh retries
                logger.exception("siren: publishing the buzzer state failed")
        else:
            self._published = state
        await self._broadcaster.broadcast({"type": EVENT_TYPE, "data": siren_to_dict(state, at)})

    def _schedule_wake_up(self, seconds: float) -> None:
        self._cancel_wake_up()

        async def wake_up() -> None:
            await self._sleep(seconds)
            try:
                await self.refresh()  # the mute has expired: the siren comes back if needed
            except Exception:  # noqa: BLE001 - try again shortly rather than stay silent for good
                logger.exception("siren: wake-up refresh failed")
            if self._state.muted_until is not None:
                # Still muted (clock stepped back, or the refresh failed): come back later.
                remaining = (self._state.muted_until - self._clock()).total_seconds()
                self._schedule_wake_up(max(1.0, remaining))

        self._wake_up = asyncio.create_task(wake_up(), name="siren-wake-up")

    def _cancel_wake_up(self) -> None:
        task, self._wake_up = self._wake_up, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
