"""Alerts: a reading left its bounds; the alert lives until a reading comes back inside them."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from app.domain.sensor_reading import SensorReading

Metric = Literal["temperature", "humidity", "gas"]
Direction = Literal["low", "high"]
METRICS: tuple[Metric, ...] = ("temperature", "humidity", "gas")

# Hysteresis: an open alert closes only once the value is this far back inside the bound.
TEMPERATURE_MARGIN_C = 0.5
HUMIDITY_MARGIN_PCT = 2.0
GAS_MARGIN_RATIO = 0.05


@dataclass(frozen=True, slots=True)
class Thresholds:
    temperature: tuple[float, float]  # (min, max) °C
    humidity: tuple[float, float]  # (min, max) %
    gas_max: int | None  # mV; None → only the device's own alert flag counts

    def __post_init__(self) -> None:
        for name, (low, high) in (("temperature", self.temperature), ("humidity", self.humidity)):
            if not low < high:
                raise ValueError(f"{name} bounds must satisfy min < max (got {low:g} ≥ {high:g})")


DEFAULT_THRESHOLDS = Thresholds(temperature=(10.0, 30.0), humidity=(20.0, 70.0), gas_max=None)


@dataclass(frozen=True, slots=True)
class Violation:
    metric: Metric
    direction: Direction
    threshold: float
    value: float


@dataclass(frozen=True, slots=True)
class Alert:
    id: UUID
    device_id: str
    metric: Metric
    direction: Direction
    threshold: float
    opened_at: datetime
    opened_value: float
    peak_value: float
    resolved_at: datetime | None
    resolved_value: float | None

    @classmethod
    def open(
        cls,
        *,
        device_id: str,
        metric: Metric,
        direction: Direction,
        threshold: float,
        at: datetime,
        value: float,
    ) -> Alert:
        return cls(
            id=uuid4(),
            device_id=device_id,
            metric=metric,
            direction=direction,
            threshold=threshold,
            opened_at=at,
            opened_value=value,
            peak_value=value,
            resolved_at=None,
            resolved_value=None,
        )

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None

    def worsen(self, value: float) -> Alert:
        """The same alert with `value` as peak when it is worse than the current one."""
        worse = value > self.peak_value if self.direction == "high" else value < self.peak_value
        return replace(self, peak_value=value) if worse else self

    def resolve(self, at: datetime, value: float) -> Alert:
        return replace(self, resolved_at=at, resolved_value=value)


def _bounded(metric: Metric, value: float | None, bounds: tuple[float, float]) -> Violation | None:
    if value is None:
        return None
    low, high = bounds
    if value < low:
        return Violation(metric, "low", low, value)
    if value > high:
        return Violation(metric, "high", high, value)
    return None


def _gas(reading: SensorReading, t: Thresholds) -> Violation | None:
    level = float(reading.gas_level) if reading.gas_level is not None else 0.0
    over_bound = (
        t.gas_max is not None and reading.gas_level is not None and reading.gas_level > t.gas_max
    )
    if over_bound:
        assert t.gas_max is not None
        return Violation("gas", "high", float(t.gas_max), level)
    if reading.gas_alert:
        # The device's own flag: no bound to compare with, threshold 0 reads as « alerte ESP ».
        return Violation("gas", "high", 0.0, level)
    return None


def violations(reading: SensorReading, t: Thresholds) -> dict[Metric, Violation | None]:
    """Which bounds this reading breaks; a missing value breaks nothing (we do not know)."""
    return {
        "temperature": _bounded("temperature", reading.temperature_c, t.temperature),
        "humidity": _bounded("humidity", reading.humidity_pct, t.humidity),
        "gas": _gas(reading, t),
    }


def _inside_with_margin(
    alert: Alert, value: float | None, bounds: tuple[float, float], margin: float
) -> bool:
    if value is None:
        return False
    low, high = bounds
    return value <= high - margin if alert.direction == "high" else value >= low + margin


def back_in_range(alert: Alert, reading: SensorReading, t: Thresholds) -> bool:
    """True when `reading` is far enough inside the bound to close `alert` (hysteresis)."""
    if alert.metric == "temperature":
        return _inside_with_margin(
            alert, reading.temperature_c, t.temperature, TEMPERATURE_MARGIN_C
        )
    if alert.metric == "humidity":
        return _inside_with_margin(alert, reading.humidity_pct, t.humidity, HUMIDITY_MARGIN_PCT)
    if reading.gas_alert:
        return False
    if t.gas_max is None:
        return True
    if reading.gas_level is None:
        return False
    return reading.gas_level <= t.gas_max * (1 - GAS_MARGIN_RATIO)
