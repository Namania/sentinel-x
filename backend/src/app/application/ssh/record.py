"""Store SSH connections relayed by the host agent; refusals open one `ssh` alert per IP.

The alert counts the refused attempts (`peak_value`) and resolves itself once the IP has been
quiet for `quiet_minutes`: a single background timer sleeps until the earliest deadline, resolves
what is due, and re-arms. Like the siren's wake-up, every refusal reschedules it."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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
        self._timer: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """After a restart: the open `ssh` alerts resolve `quiet_minutes` from now if silent."""
        now = self._clock()
        async with self._uow_factory() as uow:
            open_alerts = await uow.alerts.list("open", None, 500)
        for alert in open_alerts:
            if alert.metric == "ssh" and alert.device_id.startswith(DEVICE_PREFIX):
                self._last_attempt.setdefault(alert.device_id[len(DEVICE_PREFIX) :], now)
        self._arm()

    def close(self) -> None:
        self._cancel_timer()

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
        alert_event: tuple[str, Alert] | None = None
        async with self._lock:
            async with self._uow_factory() as uow:
                created = await uow.ssh_events.add(event)
                if not created:
                    await uow.commit()
                    return event, False
                if event.outcome == "refused":
                    alert_event = await self._count_refusal(uow, event)
                    self._last_attempt[event.ip] = min(event.occurred_at, now)
                await uow.commit()
        await self._broadcaster.broadcast({"type": EVENT_TYPE, "data": ssh_event_to_dict(event)})
        if alert_event is not None:
            kind, alert = alert_event
            await self._broadcaster.broadcast(
                {"type": kind, "data": AlertOutput.from_entity(alert).to_event()}
            )
            if kind == "alert.opened":
                await self._notify_alerts_changed()
            self._arm()
        return event, True

    async def _count_refusal(self, uow: UnitOfWork, event: SshEvent) -> tuple[str, Alert]:
        device_id = f"{DEVICE_PREFIX}{event.ip}"
        current = await uow.alerts.open_for(device_id, "ssh")
        if current is None:
            opened = Alert.open(
                device_id=device_id,
                metric="ssh",
                direction="high",
                threshold=0.0,
                at=event.occurred_at,
                value=1.0,
            )
            await uow.alerts.add(opened)
            return "alert.opened", opened
        worse = current.worsen(current.peak_value + 1)
        await uow.alerts.save(worse)
        return "alert.updated", worse

    async def _resolve_quiet(self) -> None:
        now = self._clock()
        due = [ip for ip, last in self._last_attempt.items() if last + self._quiet <= now]
        if not due:
            return
        resolved: list[Alert] = []
        async with self._lock:
            async with self._uow_factory() as uow:
                for ip in due:
                    current = await uow.alerts.open_for(f"{DEVICE_PREFIX}{ip}", "ssh")
                    if current is not None:
                        alert = current.resolve(at=now, value=current.peak_value)
                        await uow.alerts.save(alert)
                        resolved.append(alert)
                    self._last_attempt.pop(ip, None)
                await uow.commit()
        for alert in resolved:
            await self._broadcaster.broadcast(
                {"type": "alert.resolved", "data": AlertOutput.from_entity(alert).to_event()}
            )
        if resolved:
            await self._notify_alerts_changed()

    def _arm(self) -> None:
        self._cancel_timer()
        if not self._last_attempt:
            return
        deadline = min(self._last_attempt.values()) + self._quiet
        delay = max(0.0, (deadline - self._clock()).total_seconds())

        async def wake_up() -> None:
            await self._sleep(delay)
            try:
                await self._resolve_quiet()
            except Exception:  # noqa: BLE001 - never leave an alert open because of one error
                logger.exception("ssh alerts: resolving quiet IPs failed")
            self._arm()

        self._timer = asyncio.create_task(wake_up(), name="ssh-alerts-quiet-timer")

    def _cancel_timer(self) -> None:
        task, self._timer = self._timer, None
        if task is not None and task is not asyncio.current_task():
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
