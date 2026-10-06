from datetime import UTC, datetime, timedelta

import pytest

from app.domain.alert import (
    DEFAULT_THRESHOLDS,
    Alert,
    Thresholds,
    Violation,
    back_in_range,
    violations,
)
from app.domain.sensor_reading import SensorReading

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def reading(temp=22.0, hum=50.0, gas=400, flag=False, minutes=0) -> SensorReading:
    return SensorReading.create(
        device_id="esp-interieur",
        recorded_at=T0 + timedelta(minutes=minutes),
        temperature_c=temp,
        humidity_pct=hum,
        gas_level=gas,
        gas_alert=flag,
    )


def test_defaults_match_the_spec():
    assert DEFAULT_THRESHOLDS == Thresholds(
        temperature=(10.0, 30.0), humidity=(20.0, 70.0), gas_max=None
    )


def test_thresholds_reject_inverted_bounds():
    with pytest.raises(ValueError):
        Thresholds(temperature=(30.0, 10.0), humidity=(20.0, 70.0), gas_max=None)
    with pytest.raises(ValueError):
        Thresholds(temperature=(10.0, 30.0), humidity=(70.0, 70.0), gas_max=None)


def test_in_range_reading_has_no_violation():
    assert violations(reading(), DEFAULT_THRESHOLDS) == {
        "temperature": None,
        "humidity": None,
        "gas": None,
    }


def test_temperature_and_humidity_violations_carry_direction_and_bound():
    v = violations(reading(temp=30.4, hum=12.0), DEFAULT_THRESHOLDS)
    assert v["temperature"] == Violation("temperature", "high", 30.0, 30.4)
    assert v["humidity"] == Violation("humidity", "low", 20.0, 12.0)


def test_missing_values_are_not_violations():
    v = violations(reading(temp=None, hum=None, gas=None), DEFAULT_THRESHOLDS)
    assert v == {"temperature": None, "humidity": None, "gas": None}


def test_gas_alert_by_device_flag_has_a_zero_threshold_when_no_bound_is_set():
    v = violations(reading(gas=1800, flag=True), DEFAULT_THRESHOLDS)
    assert v["gas"] == Violation("gas", "high", 0.0, 1800.0)


def test_gas_alert_by_bound():
    t = Thresholds(temperature=(10.0, 30.0), humidity=(20.0, 70.0), gas_max=1500)
    assert violations(reading(gas=1600), t)["gas"] == Violation("gas", "high", 1500.0, 1600.0)
    assert violations(reading(gas=1500), t)["gas"] is None
    # The device flag alone says nothing about the bound: threshold 0 means « alerte ESP ».
    assert violations(reading(gas=None, flag=True), t)["gas"] == Violation("gas", "high", 0.0, 0.0)
    assert violations(reading(gas=800, flag=True), t)["gas"] == Violation("gas", "high", 0.0, 800.0)
    # Flag and level over the bound: the bound is the honest threshold.
    assert violations(reading(gas=1600, flag=True), t)["gas"] == Violation(
        "gas", "high", 1500.0, 1600.0
    )


def open_alert(metric="temperature", direction="high", threshold=30.0, value=30.4) -> Alert:
    return Alert.open(
        device_id="esp-interieur",
        metric=metric,
        direction=direction,
        threshold=threshold,
        at=T0,
        value=value,
    )


def test_open_alert_fields():
    a = open_alert()
    assert a.is_open
    assert (a.opened_at, a.opened_value, a.peak_value) == (T0, 30.4, 30.4)
    assert (a.resolved_at, a.resolved_value) == (None, None)


def test_worsen_keeps_the_worst_value_per_direction():
    high = open_alert()
    assert high.worsen(31.2).peak_value == 31.2
    assert high.worsen(30.1) is high
    low = open_alert(direction="low", threshold=10.0, value=9.0)
    assert low.worsen(7.5).peak_value == 7.5
    assert low.worsen(9.5) is low


def test_resolve_closes_the_alert():
    a = open_alert()
    done = a.resolve(at=T0 + timedelta(minutes=3), value=29.1)
    assert not done.is_open
    assert done.id == a.id
    assert (done.resolved_at, done.resolved_value) == (T0 + timedelta(minutes=3), 29.1)


def test_hysteresis_keeps_the_alert_open_just_under_the_bound():
    a = open_alert()
    assert back_in_range(a, reading(temp=29.8), DEFAULT_THRESHOLDS) is False
    assert back_in_range(a, reading(temp=29.5), DEFAULT_THRESHOLDS) is True
    low = open_alert(direction="low", threshold=10.0, value=9.0)
    assert back_in_range(low, reading(temp=10.2), DEFAULT_THRESHOLDS) is False
    assert back_in_range(low, reading(temp=10.5), DEFAULT_THRESHOLDS) is True


def test_humidity_hysteresis_is_two_points():
    a = open_alert(metric="humidity", threshold=70.0, value=72.0)
    assert back_in_range(a, reading(hum=69.0), DEFAULT_THRESHOLDS) is False
    assert back_in_range(a, reading(hum=68.0), DEFAULT_THRESHOLDS) is True


def test_missing_value_never_resolves():
    a = open_alert()
    assert back_in_range(a, reading(temp=None), DEFAULT_THRESHOLDS) is False


def test_gas_resolves_when_the_flag_drops_and_the_level_is_under_the_margin():
    flag_only = open_alert(metric="gas", threshold=0.0, value=1800.0)
    assert back_in_range(flag_only, reading(gas=1800, flag=True), DEFAULT_THRESHOLDS) is False
    assert back_in_range(flag_only, reading(gas=1800, flag=False), DEFAULT_THRESHOLDS) is True
    t = Thresholds(temperature=(10.0, 30.0), humidity=(20.0, 70.0), gas_max=1500)
    bounded = open_alert(metric="gas", threshold=1500.0, value=1600.0)
    assert back_in_range(bounded, reading(gas=1450, flag=False), t) is False  # > 0.95 × 1500
    assert back_in_range(bounded, reading(gas=1425, flag=False), t) is True
    assert back_in_range(bounded, reading(gas=None, flag=False), t) is False
