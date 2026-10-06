from datetime import UTC, datetime, timedelta

import pytest

from app.domain.sensor_reading import SensorReading
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def reading(device="esp-interieur", minutes=0, temp=20.0, hum=50.0, gas=400, alert=False):
    return SensorReading.create(
        device_id=device,
        recorded_at=T0 + timedelta(minutes=minutes),
        temperature_c=temp,
        humidity_pct=hum,
        gas_level=gas,
        gas_alert=alert,
    )


@pytest.fixture
async def uow(session_factory):
    return SqlAlchemyUnitOfWork(session_factory)


async def seed(uow, readings):
    async with uow as tx:
        for r in readings:
            await tx.readings.add(r)
        await tx.commit()


async def test_lists_readings_of_one_device_in_order(uow):
    await seed(uow, [reading(minutes=2), reading(minutes=0), reading(device="esp-ext", minutes=1)])
    async with uow as tx:
        rows = await tx.readings.list("esp-interieur", T0, T0 + timedelta(hours=1), limit=10)
    assert [r.recorded_at for r in rows] == [T0, T0 + timedelta(minutes=2)]


async def test_list_respects_limit_and_window(uow):
    await seed(uow, [reading(minutes=m) for m in range(5)])
    async with uow as tx:
        rows = await tx.readings.list(
            "esp-interieur", T0 + timedelta(minutes=1), T0 + timedelta(minutes=3), limit=2
        )
    assert [r.recorded_at.minute for r in rows] == [2, 3]  # the newest two of the window


async def test_latest_returns_one_reading_per_device(uow):
    await seed(
        uow,
        [
            reading(minutes=0, temp=20),
            reading(minutes=5, temp=21),
            reading(device="esp-ext", temp=10),
        ],
    )
    async with uow as tx:
        rows = await tx.readings.latest()
    assert {(r.device_id, r.temperature_c) for r in rows} == {
        ("esp-interieur", 21.0),
        ("esp-ext", 10.0),
    }


async def test_devices_with_last_seen(uow):
    await seed(uow, [reading(minutes=0), reading(minutes=7), reading(device="esp-ext", minutes=3)])
    async with uow as tx:
        devices = await tx.readings.devices()
    assert [(d.device_id, d.last_seen.minute) for d in devices] == [
        ("esp-ext", 3),
        ("esp-interieur", 7),
    ]


async def test_aggregates_per_bucket(uow):
    await seed(
        uow,
        [
            reading(minutes=0, temp=20, hum=40, gas=400),
            reading(minutes=1, temp=22, hum=60, gas=600, alert=True),
            reading(minutes=6, temp=30, hum=50, gas=None),
        ],
    )
    async with uow as tx:
        buckets = await tx.readings.aggregate("esp-interieur", T0, T0 + timedelta(minutes=10), 300)
    assert [b.bucket_start for b in buckets] == [T0, T0 + timedelta(minutes=5)]
    first, second = buckets
    assert (first.count, first.temperature_avg, first.temperature_min, first.temperature_max) == (
        2,
        21.0,
        20.0,
        22.0,
    )
    assert (first.humidity_avg, first.gas_avg, first.gas_min, first.gas_max, first.gas_alerts) == (
        50.0,
        500.0,
        400,
        600,
        1,
    )
    assert (second.count, second.temperature_avg, second.gas_avg, second.gas_alerts) == (
        1,
        30.0,
        None,
        0,
    )


async def test_aggregate_of_an_empty_window_is_empty(uow):
    async with uow as tx:
        assert await tx.readings.aggregate("esp-interieur", T0, T0 + timedelta(hours=1), 60) == []


async def test_list_keeps_the_most_recent_readings_when_the_window_overflows_the_limit(uow):
    await seed(uow, [reading(minutes=m, temp=float(m)) for m in range(5)])
    async with uow as tx:
        rows = await tx.readings.list("esp-interieur", T0, T0 + timedelta(hours=1), limit=2)
    assert [r.temperature_c for r in rows] == [3.0, 4.0]  # oldest first, but the newest two


async def test_latest_returns_a_single_row_when_two_readings_share_a_timestamp(uow):
    await seed(uow, [reading(minutes=0, temp=20), reading(minutes=0, temp=21)])
    async with uow as tx:
        rows = await tx.readings.latest()
    assert len(rows) == 1
