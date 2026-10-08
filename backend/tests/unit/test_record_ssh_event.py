import asyncio
from datetime import UTC, datetime, timedelta

from app.application.ssh.record import RecordSshEvent, SshEventInput
from app.domain.alert import Alert
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
    for _ in range(3):
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
