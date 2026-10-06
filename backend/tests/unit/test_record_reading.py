from datetime import UTC, datetime, timedelta

import pytest

from app.application.sensors.dtos import ReadingInput
from app.application.sensors.record import RecordReading
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
