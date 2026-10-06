from datetime import UTC, datetime, timedelta

import pytest

from app.application.sensors.dtos import ReadingInput
from app.application.sensors.record import RecordReading
from app.domain.alert import Thresholds
from app.domain.errors import InvalidReading
from tests.unit.fakes import InMemoryUnitOfWork

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.events = []

    async def broadcast(self, event):
        self.events.append(event)

    async def send_to_user(self, user_id, event):
        self.events.append(event)


def make_input(**overrides):
    data = dict(
        device_id="esp-interieur",
        recorded_at=None,
        temperature_c=22.5,
        humidity_pct=48.0,
        gas_level=410,
        gas_alert=False,
    )
    data.update(overrides)
    return ReadingInput(**data)


async def test_stores_the_reading_and_broadcasts_it():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    output = await RecordReading(uow, bus, clock=lambda: NOW).execute(make_input())
    assert uow.committed
    assert [r.id for r in uow.readings.readings] == [output.id]
    assert output.recorded_at == NOW  # server time when the device sends none
    assert bus.events == [{"type": "sensor.reading", "data": output.to_event()}]
    assert bus.events[0]["data"]["recorded_at"] == "2026-10-06T09:00:00Z"  # same shape as REST
    assert bus.events[0]["data"]["id"] == str(output.id)


async def test_keeps_the_device_timestamp_when_given():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    sent_at = datetime(2026, 10, 6, 8, 59, tzinfo=UTC)
    use_case = RecordReading(uow, bus, clock=lambda: NOW)
    output = await use_case.execute(make_input(recorded_at=sent_at))
    assert output.recorded_at == sent_at


async def test_invalid_values_are_rejected_before_storage():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    with pytest.raises(InvalidReading):
        await RecordReading(uow, bus).execute(make_input(humidity_pct=101))
    assert uow.readings.readings == []
    assert bus.events == []


async def test_implausible_device_timestamps_fall_back_to_server_time():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    use_case = RecordReading(uow, bus, clock=lambda: NOW)
    far_future = NOW + timedelta(minutes=10)
    ancient = datetime(2000, 1, 1, tzinfo=UTC)  # an ESP whose clock was never set
    assert (await use_case.execute(make_input(recorded_at=far_future))).recorded_at == NOW
    assert (await use_case.execute(make_input(recorded_at=ancient))).recorded_at == NOW
    slight_drift = NOW + timedelta(minutes=2)
    assert (
        await use_case.execute(make_input(recorded_at=slight_drift))
    ).recorded_at == slight_drift


def events_of(bus, kind):
    return [e for e in bus.events if e["type"] == kind]


async def test_out_of_bounds_reading_opens_an_alert_after_the_reading_event():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    await RecordReading(uow, bus, clock=lambda: NOW).execute(make_input(temperature_c=30.4))
    assert [e["type"] for e in bus.events] == ["sensor.reading", "alert.opened"]
    opened = bus.events[1]["data"]
    assert (opened["metric"], opened["direction"], opened["threshold"]) == (
        "temperature",
        "high",
        30.0,
    )
    assert opened["opened_at"] == "2026-10-06T09:00:00Z"
    assert opened["resolved_at"] is None
    assert len(uow.alerts.alerts) == 1 and uow.alerts.alerts[0].is_open


async def test_a_worse_reading_updates_the_peak_without_an_event():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    use_case = RecordReading(uow, bus, clock=lambda: NOW)
    await use_case.execute(make_input(temperature_c=30.4))
    await use_case.execute(make_input(temperature_c=31.2))
    assert len(events_of(bus, "alert.opened")) == 1
    assert len(uow.alerts.alerts) == 1
    assert uow.alerts.alerts[0].peak_value == 31.2


async def test_just_under_the_bound_keeps_the_alert_open():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    use_case = RecordReading(uow, bus, clock=lambda: NOW)
    await use_case.execute(make_input(temperature_c=30.4))
    await use_case.execute(make_input(temperature_c=29.8))
    assert events_of(bus, "alert.resolved") == []
    assert uow.alerts.alerts[0].is_open


async def test_back_under_the_margin_resolves_with_the_reading_time_and_value():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    use_case = RecordReading(uow, bus, clock=lambda: NOW)
    await use_case.execute(make_input(temperature_c=30.4))
    later = NOW + timedelta(minutes=4)
    await use_case.execute(make_input(temperature_c=29.4, recorded_at=later))
    resolved = events_of(bus, "alert.resolved")
    assert len(resolved) == 1
    assert resolved[0]["data"]["resolved_at"] == "2026-10-06T09:04:00Z"
    assert resolved[0]["data"]["resolved_value"] == 29.4
    assert not uow.alerts.alerts[0].is_open


async def test_missing_value_changes_nothing():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    use_case = RecordReading(uow, bus, clock=lambda: NOW)
    await use_case.execute(make_input(temperature_c=30.4))
    await use_case.execute(make_input(temperature_c=None))
    assert [e["type"] for e in bus.events] == ["sensor.reading", "alert.opened", "sensor.reading"]
    assert uow.alerts.alerts[0].is_open


async def test_two_metrics_out_of_bounds_open_two_alerts():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    await RecordReading(uow, bus, clock=lambda: NOW).execute(
        make_input(temperature_c=31.0, gas_level=1800, gas_alert=True)
    )
    assert [e["data"]["metric"] for e in events_of(bus, "alert.opened")] == ["temperature", "gas"]


async def test_custom_thresholds_are_honoured():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    t = Thresholds(temperature=(10.0, 25.0), humidity=(20.0, 70.0), gas_max=None)
    await RecordReading(uow, bus, thresholds=t, clock=lambda: NOW).execute(
        make_input(temperature_c=26.0)
    )
    assert len(events_of(bus, "alert.opened")) == 1


async def test_a_flip_to_the_other_bound_resolves_and_reopens_in_one_reading():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    use_case = RecordReading(uow, bus, clock=lambda: NOW)
    await use_case.execute(make_input(humidity_pct=12.0))
    later = NOW + timedelta(minutes=1)
    await use_case.execute(make_input(humidity_pct=75.0, recorded_at=later))
    kinds = [e["type"] for e in bus.events]
    assert kinds == [
        "sensor.reading",
        "alert.opened",
        "sensor.reading",
        "alert.resolved",
        "alert.opened",
    ]
    low, high = uow.alerts.alerts
    assert (low.direction, low.is_open, low.resolved_value) == ("low", False, 75.0)
    assert (high.direction, high.is_open, high.threshold, high.opened_at) == (
        "high",
        True,
        70.0,
        later,
    )


async def test_one_repository_lookup_per_reading():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    await RecordReading(uow, bus, clock=lambda: NOW).execute(make_input())
    assert uow.alerts.lookups == 1
