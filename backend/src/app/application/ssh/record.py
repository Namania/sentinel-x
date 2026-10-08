"""Store SSH connections relayed by the host agent; refusals open one `ssh` alert per IP.

The alert counts the refused attempts (`peak_value`) and resolves itself once the IP has been
quiet for `quiet_minutes`. One long-lived timer task sleeps until the earliest deadline, resolves
what is due, and goes back to sleep; a new refusal wakes it (an asyncio.Event) so it recomputes
its deadline. The timer is never cancelled mid-work: cancelling a task inside its transaction
could leave an alert open with nobody left to close it.

A refusal older than the quiet window (the agent replays the journal after a restart, or the API
was down) is history: it is stored as an already-resolved alert, merged with the previous
attempts of that IP when they fall in the same window, and wakes neither the timer nor the siren.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from app.application.alerts.dtos import AlertOutput
from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.ports.unit_of_work import UnitOfWork
from app.application.sensors.record import MAX_AGE, MAX_FUTURE_DRIFT
from app.application.ssh.dtos import ssh_event_to_dict
from app.domain.alert import Alert
from app.domain.ssh_event import Outcome, Reason, SshEvent

logger = logging.getLogger(__name__)

EVENT_TYPE = "ssh.event"
DEVICE_PREFIX = "ip:"
# After a failed resolution (database away), wait this long before trying again.
RETRY_DELAY_S = 30.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SshEventInput:
    journal_id: str
    occurred_at: datetime
    outcome: Outcome
    username: str
    ip: str
    port: int
    method: str | None = None
    key_fingerprint: str | None = None
    key_comment: str | None = None
    reason: Reason | None = None


@dataclass(frozen=True, slots=True)
class _AlertChange:
    kind: str  # "alert.opened" | "alert.updated"
    alert: Alert
    live: bool  # True when the alert is (still) open: arms the timer, wakes the siren on open


class RecordSshEvent:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        broadcaster: EventBroadcaster,
        on_alerts_changed: Callable[[], Awaitable[None]] | None = None,
        quiet_minutes: int = 10,
        clock: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._uow_factory = uow_factory
        self._broadcaster = broadcaster
        self._on_alerts_changed = on_alerts_changed
        self._quiet = timedelta(minutes=quiet_minutes)
        self._clock = clock
        self._sleep = sleep
        self._last_attempt: dict[str, datetime] = {}  # ip → last refused attempt (≤ now)
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._timer: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """After a restart: the open `ssh` alerts resolve `quiet_minutes` from now if silent."""
        now = self._clock()
        async with self._uow_factory() as uow:
            open_alerts = await uow.alerts.list("open", None, 500)
        for alert in open_alerts:
            if alert.metric == "ssh" and alert.device_id.startswith(DEVICE_PREFIX):
                self._last_attempt.setdefault(alert.device_id[len(DEVICE_PREFIX) :], now)
        if self._last_attempt:
            self._wake_timer()

    def close(self) -> None:
        task, self._timer = self._timer, None
        if task is not None:
            task.cancel()

    async def record(self, data: SshEventInput) -> tuple[SshEvent, bool]:
        """Store the event; returns (event, created). A duplicate journal_id changes nothing."""
        now = self._clock()
        event = SshEvent.create(
            journal_id=data.journal_id,
            occurred_at=self._plausible(data.occurred_at, now),
            outcome=data.outcome,
            username=data.username,
            ip=data.ip,
            port=data.port,
            method=data.method,
            key_fingerprint=data.key_fingerprint,
            key_comment=data.key_comment,
            reason=data.reason,
        )
        change: _AlertChange | None = None
        async with self._lock:
            async with self._uow_factory() as uow:
                created = await uow.ssh_events.add(event)
                if not created:
                    await uow.commit()
                    return event, False
                if event.outcome == "refused":
                    change = await self._count_refusal(uow, event, now)
                await uow.commit()
            if change is not None and change.live:
                # Inside the lock: the timer reads this map to pick its deadline. A late event
                # (API downtime) never moves the deadline backwards.
                seen = min(event.occurred_at, now)
                self._last_attempt[event.ip] = max(self._last_attempt.get(event.ip, seen), seen)
        await self._broadcaster.broadcast({"type": EVENT_TYPE, "data": ssh_event_to_dict(event)})
        if change is not None:
            await self._broadcaster.broadcast(
                {"type": change.kind, "data": AlertOutput.from_entity(change.alert).to_event()}
            )
            if change.live:
                if change.kind == "alert.opened":
                    await self._notify_alerts_changed()
                self._wake_timer()
        return event, True

    async def _count_refusal(self, uow: UnitOfWork, event: SshEvent, now: datetime) -> _AlertChange:
        device_id = f"{DEVICE_PREFIX}{event.ip}"
        current = await uow.alerts.latest_for(device_id, "ssh")
        if current is not None and current.is_open:
            worse = current.worsen(current.peak_value + 1)
            await uow.alerts.save(worse)
            return _AlertChange("alert.updated", worse, live=True)
        if event.occurred_at + self._quiet <= now:
            # History (replayed journal, API downtime): never an open alert, never the siren.
            end = min(event.occurred_at + self._quiet, now)
            if (
                current is not None
                and current.resolved_at is not None
                and current.resolved_at >= event.occurred_at
            ):
                count = current.peak_value + 1
                merged = replace(
                    current,
                    peak_value=count,
                    resolved_at=max(current.resolved_at, end),
                    resolved_value=count,
                )
                await uow.alerts.save(merged)
                return _AlertChange("alert.updated", merged, live=False)
            past = self._open_alert(device_id, event.occurred_at).resolve(at=end, value=1.0)
            await uow.alerts.add(past)
            return _AlertChange("alert.updated", past, live=False)
        opened = self._open_alert(device_id, event.occurred_at)
        await uow.alerts.add(opened)
        return _AlertChange("alert.opened", opened, live=True)

    @staticmethod
    def _open_alert(device_id: str, at: datetime) -> Alert:
        return Alert.open(
            device_id=device_id, metric="ssh", direction="high", threshold=0.0, at=at, value=1.0
        )

    async def _resolve_quiet(self) -> None:
        resolved: list[Alert] = []
        async with self._lock:
            now = self._clock()
            due = [ip for ip, last in self._last_attempt.items() if last + self._quiet <= now]
            if not due:
                return
            async with self._uow_factory() as uow:
                for ip in due:
                    current = await uow.alerts.open_for(f"{DEVICE_PREFIX}{ip}", "ssh")
                    if current is not None:
                        alert = current.resolve(at=now, value=current.peak_value)
                        await uow.alerts.save(alert)
                        resolved.append(alert)
                await uow.commit()
            # Only once the database agrees: a failed commit keeps the IP due for the next try.
            for ip in due:
                self._last_attempt.pop(ip, None)
        for alert in resolved:
            await self._broadcaster.broadcast(
                {"type": "alert.resolved", "data": AlertOutput.from_entity(alert).to_event()}
            )
        if resolved:
            await self._notify_alerts_changed()

    def _wake_timer(self) -> None:
        if self._timer is None or self._timer.done():
            self._timer = asyncio.create_task(self._run_timer(), name="ssh-alerts-quiet-timer")
        self._wake.set()

    async def _run_timer(self) -> None:
        while True:
            self._wake.clear()
            if not self._last_attempt:
                await self._wake.wait()
                continue
            deadline = min(self._last_attempt.values()) + self._quiet
            delay = max(0.0, (deadline - self._clock()).total_seconds())
            # A deadline already passed is handled right away, without a 0 s sleep hop.
            if delay > 0 and not await self._sleep_or_wake(delay):
                continue  # woken by a new refusal: recompute the deadline
            try:
                await self._resolve_quiet()
            except Exception:  # noqa: BLE001 - never leave an alert open because of one error
                logger.exception("ssh alerts: resolving quiet IPs failed")
                await self._sleep_or_wake(RETRY_DELAY_S)

    async def _sleep_or_wake(self, seconds: float) -> bool:
        """Sleep `seconds`; True when the sleep completed, False when a refusal woke the timer."""
        sleeping = asyncio.ensure_future(self._sleep(seconds))
        waking = asyncio.ensure_future(self._wake.wait())
        try:
            await asyncio.wait({sleeping, waking}, return_when=asyncio.FIRST_COMPLETED)
            return sleeping.done() and not sleeping.cancelled()
        finally:
            for task in (sleeping, waking):
                if not task.done():
                    task.cancel()

    async def _notify_alerts_changed(self) -> None:
        if self._on_alerts_changed is None:
            return
        try:
            await self._on_alerts_changed()
        except Exception:  # noqa: BLE001 - the event is stored; the siren catches up later
            logger.exception("alert change hook failed")

    @staticmethod
    def _plausible(occurred_at: datetime, now: datetime) -> datetime:
        moment = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
        moment = moment.astimezone(UTC)
        if moment > now + MAX_FUTURE_DRIFT or moment < now - MAX_AGE:
            return now
        return moment
