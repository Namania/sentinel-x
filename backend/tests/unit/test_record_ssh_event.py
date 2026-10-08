import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.application.ssh.record import RecordSshEvent, SshEventInput
from app.domain.alert import Alert
from app.domain.errors import AlertNotClosable, AlertNotFound
from tests.unit.fakes import InMemoryUnitOfWork, RecordingBroadcaster

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class Hook:
    def __init__(self, fail=False) -> None:
        self.calls = 0
        self.fail = fail

    async def __call__(self) -> None:
        self.calls += 1
        if self.fail:
            raise ConnectionError("broker down")


def build(hook: Hook | None = None, quiet_minutes=10):
    uow = InMemoryUnitOfWork()
    bus = RecordingBroadcaster()
    clock = Clock()
    sleeps: list[float] = []
    wakes: list[asyncio.Future[None]] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        wakes.append(future)
        await future

    service = RecordSshEvent(
        uow_factory=lambda: uow,
        broadcaster=bus,
        on_alerts_changed=hook,
        quiet_minutes=quiet_minutes,
        clock=clock,
        sleep=sleep,
    )
    return service, uow, bus, clock, sleeps, wakes


def refused(journal_id="c1", ip="203.0.113.5", at=NOW, reason="key_rejected") -> SshEventInput:
    return SshEventInput(
        journal_id=journal_id,
        occurred_at=at,
        outcome="refused",
        username="root",
        ip=ip,
        port=51234,
        reason=reason,
    )


def accepted(journal_id="a1", at=NOW) -> SshEventInput:
    return SshEventInput(
        journal_id=journal_id,
        occurred_at=at,
        outcome="accepted",
        username="sentinel-x",
        ip="192.168.0.18",
        port=49513,
        method="publickey",
        key_fingerprint="SHA256:Wqjh",
        key_comment="mael.namania@gmail.com",
    )


def types(bus) -> list[str]:
    return [e["type"] for e in bus.broadcasts]


async def settle() -> None:
    # The timer hops through Event.wait, asyncio.wait and a fresh sleep task: several ticks.
    for _ in range(10):
        await asyncio.sleep(0)


async def test_an_accepted_connection_is_stored_and_broadcast_without_an_alert():
    service, uow, bus, _, _, _ = build(Hook())
    event, created = await service.record(accepted())
    assert created is True
    assert [e.journal_id for e in uow.ssh_events.events] == ["a1"]
    assert uow.alerts.alerts == []
    assert types(bus) == ["ssh.event"]
    assert bus.broadcasts[0]["data"]["key_comment"] == "mael.namania@gmail.com"
    assert bus.broadcasts[0]["data"]["occurred_at"] == "2026-10-08T09:00:00Z"
    assert bus.broadcasts[0]["data"]["id"] == str(event.id)


async def test_a_refusal_opens_one_alert_per_ip_and_wakes_the_siren():
    hook = Hook()
    service, uow, bus, _, sleeps, _ = build(hook)
    await service.record(refused())
    await settle()
    (alert,) = uow.alerts.alerts
    assert (alert.device_id, alert.metric, alert.direction) == ("ip:203.0.113.5", "ssh", "high")
    assert (alert.threshold, alert.opened_value, alert.peak_value) == (0.0, 1.0, 1.0)
    assert alert.opened_at == NOW
    assert types(bus) == ["ssh.event", "alert.opened"]
    assert hook.calls == 1
    assert sleeps == [10 * 60]


async def test_a_second_refusal_from_the_same_ip_increments_the_alert():
    hook = Hook()
    service, uow, bus, clock, sleeps, _ = build(hook)
    await service.record(refused("c1"))
    clock.now = NOW + timedelta(minutes=3)
    await service.record(refused("c2", at=clock.now))
    await settle()
    assert len(uow.alerts.alerts) == 1
    assert uow.alerts.alerts[0].peak_value == 2.0
    assert types(bus) == ["ssh.event", "alert.opened", "ssh.event", "alert.updated"]
    assert bus.broadcasts[-1]["data"]["peak_value"] == 2.0
    assert hook.calls == 1  # the siren only cares about open/close
    assert sleeps[-1] == 10 * 60  # re-armed from the latest attempt


async def test_refusals_from_two_ips_open_two_alerts():
    service, uow, _, _, _, _ = build()
    await service.record(refused("c1", ip="203.0.113.5"))
    await service.record(refused("c2", ip="198.51.100.7"))
    assert sorted(a.device_id for a in uow.alerts.alerts) == ["ip:198.51.100.7", "ip:203.0.113.5"]


async def test_the_alert_resolves_after_quiet_minutes():
    hook = Hook()
    service, uow, bus, clock, _, wakes = build(hook)
    await service.record(refused("c1"))
    await service.record(refused("c2", at=NOW + timedelta(minutes=1)))
    await settle()
    clock.now = NOW + timedelta(minutes=11)
    wakes[-1].set_result(None)
    await settle()
    (alert,) = uow.alerts.alerts
    assert alert.resolved_at == clock.now
    assert alert.resolved_value == 2.0
    assert types(bus)[-1] == "alert.resolved"
    assert hook.calls == 2


async def test_a_refusal_during_the_quiet_window_postpones_the_resolution():
    service, uow, _, clock, sleeps, wakes = build()
    await service.record(refused("c1"))
    await settle()
    clock.now = NOW + timedelta(minutes=9)
    await service.record(refused("c2", at=clock.now))
    await settle()
    assert sleeps[-1] == 10 * 60
    # The first timer was cancelled: resolving it would be wrong.
    assert wakes[0].cancelled()
    clock.now = NOW + timedelta(minutes=10, seconds=30)
    wakes[-1].set_result(None)
    await settle()
    assert uow.alerts.alerts[0].is_open  # 9 min + 1:30 < 10 min of quiet
    assert sleeps[-1] > 0  # re-armed for the remaining time


async def test_a_future_timestamp_does_not_delay_the_resolution():
    service, uow, _, clock, sleeps, wakes = build()
    await service.record(refused("c1", at=NOW + timedelta(days=2)))
    await settle()
    assert sleeps == [10 * 60]  # measured from now, not from the bogus timestamp
    clock.now = NOW + timedelta(minutes=10)
    wakes[-1].set_result(None)
    await settle()
    assert not uow.alerts.alerts[0].is_open


async def test_a_duplicate_journal_id_is_acknowledged_but_changes_nothing():
    service, uow, bus, _, _, _ = build()
    await service.record(refused("c1"))
    event, created = await service.record(refused("c1"))
    assert created is False
    assert event.journal_id == "c1"
    assert len(uow.ssh_events.events) == 1
    assert uow.alerts.alerts[0].peak_value == 1.0
    assert types(bus) == ["ssh.event", "alert.opened"]


async def test_start_resolves_alerts_left_open_after_a_restart():
    service, uow, bus, clock, sleeps, wakes = build()
    stale = Alert.open(
        device_id="ip:203.0.113.5",
        metric="ssh",
        direction="high",
        threshold=0.0,
        at=NOW - timedelta(hours=5),
        value=3.0,
    )
    await uow.alerts.add(stale)
    await service.start()
    await settle()
    assert sleeps == [10 * 60]
    clock.now = NOW + timedelta(minutes=10)
    wakes[-1].set_result(None)
    await settle()
    assert uow.alerts.alerts[0].resolved_value == 3.0
    assert types(bus) == ["alert.resolved"]


async def test_a_failing_hook_does_not_lose_the_event():
    service, uow, bus, _, _, _ = build(Hook(fail=True))
    _, created = await service.record(refused("c1"))
    assert created is True
    assert len(uow.ssh_events.events) == 1
    assert types(bus) == ["ssh.event", "alert.opened"]


async def test_close_cancels_the_timer():
    service, _, _, _, _, wakes = build()
    await service.record(refused("c1"))
    await settle()
    service.close()
    await settle()
    assert wakes[0].cancelled()


class GatedCommitUow(InMemoryUnitOfWork):
    """`commit` waits for the test to open the gate: the timer can be frozen mid-transaction."""

    def __init__(self) -> None:
        super().__init__()
        self.gate: asyncio.Future[None] | None = None

    async def commit(self) -> None:
        if self.gate is not None and not self.gate.done():
            await self.gate
        await super().commit()


async def test_a_database_error_in_the_timer_backs_off_instead_of_spinning():
    service, uow, _, clock, sleeps, wakes = build()
    await service.record(refused("c1"))
    await settle()
    clock.now = NOW + timedelta(minutes=10)
    broken = uow.alerts

    class Exploding:
        async def open_for(self, *args):
            raise ConnectionError("database away")

        def __getattr__(self, name):
            return getattr(broken, name)

    uow.alerts = Exploding()
    wakes[-1].set_result(None)
    await settle()
    # Not a 0 s retry: the timer waits a while before trying the database again.
    assert sleeps[-1] >= 30
    uow.alerts = broken
    wakes[-1].set_result(None)
    await settle()
    assert not uow.alerts.alerts[0].is_open


async def test_a_refusal_during_the_resolution_does_not_cancel_it():
    uow = GatedCommitUow()
    bus = RecordingBroadcaster()
    clock = Clock()
    sleeps: list[float] = []
    wakes: list[asyncio.Future[None]] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        wakes.append(future)
        await future

    service = RecordSshEvent(lambda: uow, bus, quiet_minutes=10, clock=clock, sleep=sleep)
    await service.record(refused("c1", ip="203.0.113.5"))
    await settle()
    clock.now = NOW + timedelta(minutes=11)
    uow.gate = asyncio.get_running_loop().create_future()
    wakes[-1].set_result(None)
    await settle()  # the timer is now inside its transaction, waiting on the gate
    other = asyncio.create_task(service.record(refused("c2", ip="198.51.100.7", at=clock.now)))
    await settle()
    uow.gate.set_result(None)
    uow.gate = None
    await other
    await settle()
    by_ip = {a.device_id: a for a in uow.alerts.alerts}
    assert not by_ip["ip:203.0.113.5"].is_open  # the resolution went through
    assert by_ip["ip:198.51.100.7"].is_open
    assert types(bus).count("alert.resolved") == 1
    assert sleeps[-1] == 10 * 60  # re-armed for the second ip, timer still alive
    service.close()


async def test_stale_refusals_are_recorded_as_history_without_waking_anyone():
    hook = Hook()
    service, uow, bus, _, sleeps, _ = build(hook)
    first = NOW - timedelta(hours=23)
    for i in range(5):
        await service.record(refused(f"c{i}", at=first + timedelta(minutes=2 * i)))
    await settle()
    (alert,) = uow.alerts.alerts
    assert alert.peak_value == 5.0
    assert not alert.is_open
    assert alert.opened_at == first
    assert alert.resolved_at == first + timedelta(minutes=8) + timedelta(minutes=10)
    assert alert.resolved_value == 5.0
    assert "alert.opened" not in types(bus)
    assert types(bus).count("ssh.event") == 5
    assert hook.calls == 0
    assert sleeps == []  # nothing to resolve later


async def test_a_stale_refusal_outside_the_previous_window_opens_a_second_history_alert():
    service, uow, _, _, _, _ = build()
    first = NOW - timedelta(hours=23)
    await service.record(refused("c1", at=first))
    await service.record(refused("c2", at=first + timedelta(minutes=30)))
    assert len(uow.alerts.alerts) == 2
    assert all(not a.is_open for a in uow.alerts.alerts)


async def test_a_stale_refusal_still_counts_into_an_open_alert_and_hastens_its_end():
    """The API was down: a refusal from 15 min ago arrives while the IP's alert is open."""
    service, uow, _, clock, sleeps, _ = build()
    await service.record(refused("c1"))
    await settle()
    clock.now = NOW + timedelta(minutes=5)
    await service.record(refused("c2", at=NOW - timedelta(minutes=15)))
    await settle()
    (alert,) = uow.alerts.alerts
    assert alert.is_open and alert.peak_value == 2.0
    assert sleeps[-1] == pytest.approx(5 * 60)  # still 10 min after the newest attempt (NOW)


async def test_resolve_closes_an_ssh_alert_by_hand_and_forgets_the_ip():
    hook = Hook()
    service, uow, bus, clock, sleeps, wakes = build(hook)
    await service.record(refused("c1"))
    await service.record(refused("c2", at=NOW + timedelta(minutes=1)))
    await settle()
    clock.now = NOW + timedelta(minutes=2)
    closed = await service.resolve(uow.alerts.alerts[0].id, by=uuid4())
    await settle()
    assert closed.resolved_at == clock.now and closed.resolved_value == 2.0
    assert not uow.alerts.alerts[0].is_open
    assert types(bus)[-1] == "alert.resolved"
    assert hook.calls == 2
    # The timer has nothing left to do: its pending sleep was abandoned, no new one armed.
    assert wakes[-1].cancelled() and len(sleeps) == len(wakes)
    # The next refusal from that ip is a new alert, not a reopening.
    await service.record(refused("c3", at=clock.now))
    assert len(uow.alerts.alerts) == 2 and uow.alerts.alerts[1].is_open


async def test_resolve_refuses_unknown_sensor_or_closed_alerts():
    service, uow, bus, _, _, _ = build()
    with pytest.raises(AlertNotFound):
        await service.resolve(uuid4(), by=uuid4())
    sensor = Alert.open(
        device_id="esp-interieur", metric="gas", direction="high", threshold=0.0, at=NOW, value=1.0
    )
    await uow.alerts.add(sensor)
    with pytest.raises(AlertNotClosable):
        await service.resolve(sensor.id, by=uuid4())
    await service.record(refused("c1"))
    ssh = uow.alerts.alerts[1]
    await service.resolve(ssh.id, by=uuid4())
    with pytest.raises(AlertNotClosable):
        await service.resolve(ssh.id, by=uuid4())
    assert sensor.is_open and types(bus).count("alert.resolved") == 1
