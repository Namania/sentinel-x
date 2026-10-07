import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.application.alerts.siren import Siren, siren_to_dict
from app.domain.alert import Alert
from app.domain.siren import SirenState, parse_triggers
from tests.unit.fakes import InMemoryUnitOfWork

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
TRIGGERS = parse_triggers("gas,temperature:high")


class RecordingPublisher:
    def __init__(self, fail=False) -> None:
        self.published: list[tuple[SirenState, datetime]] = []
        self.fail = fail

    async def publish(self, state, at):
        if self.fail:
            raise ConnectionError("broker down")
        self.published.append((state, at))


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.events = []

    async def broadcast(self, event):
        self.events.append(event)

    async def send_to_user(self, user_id, event):
        self.events.append(event)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def gas_alert() -> Alert:
    return Alert.open(
        device_id="esp-interieur",
        metric="gas",
        direction="high",
        threshold=0.0,
        at=NOW,
        value=1800.0,
    )


def build(fail=False):
    uow = InMemoryUnitOfWork()
    publisher = RecordingPublisher(fail)
    bus = RecordingBroadcaster()
    clock = Clock()
    sleeps: list[float] = []
    wake = asyncio.Event()

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await wake.wait()

    siren = Siren(lambda: uow, publisher, bus, TRIGGERS, mute_minutes=15, clock=clock, sleep=sleep)
    return siren, uow, publisher, bus, clock, sleeps, wake


async def test_the_first_refresh_publishes_even_when_silent():
    siren, _, publisher, bus, _, _, _ = build()
    state = await siren.refresh()
    assert state == SirenState(on=False, reason=None, open=0, muted_until=None)
    assert [s.on for s, _ in publisher.published] == [False]
    assert bus.events[0]["type"] == "siren.state"
    assert bus.events[0]["data"] == siren_to_dict(state, NOW)
    assert bus.events[0]["data"]["at"] == "2026-10-07T09:00:00Z"
    assert list(bus.events[0]["data"])[0] == "on"


async def test_refresh_publishes_only_on_change():
    siren, uow, publisher, _, _, _, _ = build()
    await siren.refresh()
    await siren.refresh()
    assert len(publisher.published) == 1
    await uow.alerts.add(gas_alert())
    state = await siren.refresh()
    assert (state.on, state.reason) == (True, "gas")
    assert len(publisher.published) == 2
    await siren.refresh()
    assert len(publisher.published) == 2


async def test_mute_silences_and_schedules_the_wake_up():
    siren, uow, publisher, _, clock, sleeps, wake = build()
    await uow.alerts.add(gas_alert())
    await siren.refresh()
    state = await siren.mute(by=uuid4())
    await asyncio.sleep(0)  # the wake-up task starts on the next loop tick
    assert state.on is False
    assert state.muted_until == NOW + timedelta(minutes=15)
    assert publisher.published[-1][0].on is False
    assert sleeps == [15 * 60]
    # The mute expires: the siren comes back on its own because the alert is still open.
    clock.now = NOW + timedelta(minutes=15, seconds=1)
    wake.set()
    await asyncio.sleep(0.01)
    assert publisher.published[-1][0].on is True
    assert siren.state.muted_until is None


async def test_a_second_mute_replaces_the_first_wake_up():
    siren, uow, _, _, clock, sleeps, _ = build()
    await uow.alerts.add(gas_alert())
    await siren.refresh()
    await siren.mute(by=uuid4())
    await asyncio.sleep(0)
    clock.now = NOW + timedelta(minutes=5)
    state = await siren.mute(by=uuid4())
    await asyncio.sleep(0)
    assert state.muted_until == NOW + timedelta(minutes=20)
    assert sleeps == [15 * 60, 15 * 60]
    siren.close()


async def test_unmute_restores_the_siren():
    siren, uow, publisher, _, _, _, _ = build()
    await uow.alerts.add(gas_alert())
    await siren.refresh()
    await siren.mute(by=uuid4())
    state = await siren.unmute(by=uuid4())
    assert (state.on, state.muted_until) == (True, None)
    assert publisher.published[-1][0].on is True
    siren.close()


async def test_a_failing_publisher_does_not_break_refresh(caplog):
    siren, uow, _, bus, _, _, _ = build(fail=True)
    await uow.alerts.add(gas_alert())
    state = await siren.refresh()
    assert state.on is True
    assert bus.events[-1]["type"] == "siren.state"
    assert "broker down" in caplog.text
