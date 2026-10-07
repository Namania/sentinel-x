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


class SlowAlerts:
    """Wraps the in-memory alert repository: `list` yields for a scripted delay."""

    def __init__(self, inner, delays: list[float]) -> None:
        self._inner = inner
        self._delays = delays

    async def list(self, status, device_id, limit):
        await asyncio.sleep(self._delays.pop(0) if self._delays else 0)
        return await self._inner.list(status, device_id, limit)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class FailingOnce:
    """A unit-of-work factory that raises on the next use when `fail_next` is set."""

    def __init__(self, uow) -> None:
        self.uow = uow
        self.fail_next = False

    def __call__(self):
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("database away")
        return self.uow


def build(fail=False, delays: list[float] | None = None):
    uow = InMemoryUnitOfWork()
    if delays is not None:
        uow.alerts = SlowAlerts(uow.alerts, delays)
    factory = FailingOnce(uow)
    publisher = RecordingPublisher(fail)
    bus = RecordingBroadcaster()
    clock = Clock()
    sleeps: list[float] = []
    wakes: list[asyncio.Future[None]] = []  # one per sleep; the test resolves the one it wants

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        wakes.append(future)
        await future

    siren = Siren(factory, publisher, bus, TRIGGERS, mute_minutes=15, clock=clock, sleep=sleep)
    siren.factory = factory  # type: ignore[attr-defined] - test hook
    return siren, uow, publisher, bus, clock, sleeps, wakes


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
    siren, uow, publisher, _, clock, sleeps, wakes = build()
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
    wakes[0].set_result(None)
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


async def test_a_failed_publish_is_retried_at_the_next_refresh_even_without_change(caplog):
    siren, uow, publisher, _, _, _, _ = build(fail=True)
    await uow.alerts.add(gas_alert())
    await siren.refresh()
    assert publisher.published == []
    publisher.fail = False
    await siren.refresh()  # nothing changed, but the broker never got the `on`
    assert [s.on for s, _ in publisher.published] == [True]
    await siren.refresh()
    assert len(publisher.published) == 1


async def test_the_wake_up_survives_a_failing_refresh_and_tries_again(caplog):
    siren, uow, publisher, _, clock, sleeps, wakes = build()
    await uow.alerts.add(gas_alert())
    await siren.refresh()
    await siren.mute(by=uuid4())
    await asyncio.sleep(0)
    siren.factory.fail_next = True  # the database is away when the mute expires
    clock.now = NOW + timedelta(minutes=15, seconds=1)
    wakes[0].set_result(None)
    await asyncio.sleep(0.01)
    assert "database away" in caplog.text
    assert publisher.published[-1][0].on is False  # not back yet
    assert sleeps == [15 * 60, 1.0]  # rescheduled, soon
    wakes[1].set_result(None)
    await asyncio.sleep(0.01)
    assert publisher.published[-1][0].on is True
    assert siren.state.muted_until is None


async def test_concurrent_refreshes_publish_the_newest_state_last():
    # The first refresh reads before the alert lands but finishes after the second one.
    siren, uow, publisher, _, _, _, _ = build(delays=[0.03, 0.005])
    await siren.refresh()
    first = asyncio.create_task(siren.refresh())
    await asyncio.sleep(0.001)
    await uow.alerts.add(gas_alert())
    second = asyncio.create_task(siren.refresh())
    await asyncio.gather(first, second)
    assert siren.state.on is True
    assert publisher.published[-1][0].on is True
