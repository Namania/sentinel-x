from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.errors import InvalidReading
from app.domain.sensor_reading import SensorReading

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def make(**overrides):
    data = dict(
        device_id="esp-interieur",
        recorded_at=NOW,
        temperature_c=22.5,
        humidity_pct=48.0,
        gas_level=410,
        gas_alert=False,
    )
    data.update(overrides)
    return SensorReading.create(**data)


def test_creates_a_reading_with_an_id_and_utc_time():
    reading = make()
    assert reading.id is not None
    assert reading.recorded_at == NOW
    assert reading.device_id == "esp-interieur"


def test_converts_recorded_at_to_utc():
    paris = timezone(timedelta(hours=2))
    reading = make(recorded_at=datetime(2026, 10, 6, 11, 0, tzinfo=paris))
    assert reading.recorded_at == NOW


def test_naive_recorded_at_is_taken_as_utc():
    reading = make(recorded_at=datetime(2026, 10, 6, 9, 0))
    assert reading.recorded_at == NOW


def test_metrics_may_all_be_missing():
    reading = make(temperature_c=None, humidity_pct=None, gas_level=None)
    assert (reading.temperature_c, reading.humidity_pct, reading.gas_level) == (None, None, None)


@pytest.mark.parametrize("device_id", ["", "ESP", "esp interieur", "a" * 65, "esp_1"])
def test_rejects_bad_device_ids(device_id):
    with pytest.raises(InvalidReading):
        make(device_id=device_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature_c", -40.1),
        ("temperature_c", 125.1),
        ("humidity_pct", -0.1),
        ("humidity_pct", 100.1),
        ("gas_level", -1),
    ],
)
def test_rejects_out_of_range_values(field, value):
    with pytest.raises(InvalidReading):
        make(**{field: value})


def test_accepts_boundary_values():
    reading = make(temperature_c=-40, humidity_pct=100, gas_level=0)
    assert reading.temperature_c == -40
