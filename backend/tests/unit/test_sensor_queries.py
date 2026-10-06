from datetime import UTC, datetime, timedelta

from app.application.sensors.dtos import BucketOutput, ReadingOutput
from app.application.sensors.queries import GetLatestReadings, GetReadings, ListDevices
from app.domain.sensor_reading import SensorReading
from tests.unit.fakes import InMemoryUnitOfWork

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def seeded():
    uow = InMemoryUnitOfWork()
    rows = [("esp-interieur", 0, 20.0), ("esp-interieur", 3, 24.0), ("esp-ext", 1, 10.0)]
    for device, minutes, temp in rows:
        uow.readings.readings.append(
            SensorReading.create(
                device_id=device,
                recorded_at=T0 + timedelta(minutes=minutes),
                temperature_c=temp,
                humidity_pct=50.0,
                gas_level=400,
                gas_alert=False,
            )
        )
    return uow


async def test_raw_readings_when_no_bucket():
    rows = await GetReadings(seeded()).execute("esp-interieur", T0, T0 + timedelta(hours=1), None)
    assert all(isinstance(r, ReadingOutput) for r in rows)
    assert [r.temperature_c for r in rows] == [20.0, 24.0]


async def test_buckets_when_a_bucket_size_is_given():
    rows = await GetReadings(seeded()).execute("esp-interieur", T0, T0 + timedelta(hours=1), 300)
    assert len(rows) == 1 and isinstance(rows[0], BucketOutput)
    assert rows[0].temperature_avg == 22.0 and rows[0].count == 2


async def test_latest_and_devices():
    uow = seeded()
    latest = await GetLatestReadings(uow).execute()
    assert {(r.device_id, r.temperature_c) for r in latest} == {
        ("esp-interieur", 24.0),
        ("esp-ext", 10.0),
    }
    devices = await ListDevices(uow).execute()
    assert [d.device_id for d in devices] == ["esp-ext", "esp-interieur"]
