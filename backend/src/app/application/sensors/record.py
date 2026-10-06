from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.application.alerts.dtos import AlertOutput
from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.ports.unit_of_work import UnitOfWork
from app.application.sensors.dtos import ReadingInput, ReadingOutput
from app.domain.alert import (
    DEFAULT_THRESHOLDS,
    METRICS,
    Alert,
    Thresholds,
    back_in_range,
    violations,
)
from app.domain.sensor_reading import SensorReading, to_utc

# Devices have no reliable clock: timestamps outside this window are replaced by server time.
MAX_FUTURE_DRIFT = timedelta(minutes=5)
MAX_AGE = timedelta(days=30)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RecordReading:
    """Store one reading from a device and push it to the connected clients."""

    def __init__(
        self,
        uow: UnitOfWork,
        broadcaster: EventBroadcaster,
        thresholds: Thresholds = DEFAULT_THRESHOLDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow = uow
        self._broadcaster = broadcaster
        self._thresholds = thresholds
        self._clock = clock or _utc_now

    def _plausible_time(self, recorded_at: datetime | None) -> datetime:
        now = self._clock()
        if recorded_at is None:
            return now
        moment = to_utc(recorded_at)
        if moment > now + MAX_FUTURE_DRIFT or moment < now - MAX_AGE:
            return now
        return moment

    async def execute(self, data: ReadingInput) -> ReadingOutput:
        reading = SensorReading.create(
            device_id=data.device_id,
            recorded_at=self._plausible_time(data.recorded_at),
            temperature_c=data.temperature_c,
            humidity_pct=data.humidity_pct,
            gas_level=data.gas_level,
            gas_alert=data.gas_alert,
        )
        async with self._uow as uow:
            await uow.readings.add(reading)
            alert_events = await self._apply_alerts(uow, reading)
            await uow.commit()
        output = ReadingOutput.from_entity(reading)
        await self._broadcaster.broadcast({"type": "sensor.reading", "data": output.to_event()})
        for kind, alert in alert_events:
            await self._broadcaster.broadcast(
                {"type": kind, "data": AlertOutput.from_entity(alert).to_event()}
            )
        return output

    async def _apply_alerts(
        self, uow: UnitOfWork, reading: SensorReading
    ) -> list[tuple[str, Alert]]:
        """Open, worsen or resolve one alert per metric; returns the events to publish."""
        events: list[tuple[str, Alert]] = []
        found = violations(reading, self._thresholds)
        for metric in METRICS:
            violation = found[metric]
            current = await uow.alerts.open_for(reading.device_id, metric)
            if violation is not None and current is None:
                opened = Alert.open(
                    device_id=reading.device_id,
                    metric=metric,
                    direction=violation.direction,
                    threshold=violation.threshold,
                    at=reading.recorded_at,
                    value=violation.value,
                )
                await uow.alerts.add(opened)
                events.append(("alert.opened", opened))
            elif violation is not None and current is not None:
                worse = current.worsen(violation.value)
                if worse is not current:
                    await uow.alerts.save(worse)
            elif current is not None and back_in_range(current, reading, self._thresholds):
                resolved = current.resolve(
                    at=reading.recorded_at, value=_metric_value(reading, metric)
                )
                await uow.alerts.save(resolved)
                events.append(("alert.resolved", resolved))
        return events


def _metric_value(reading: SensorReading, metric: str) -> float:
    # back_in_range is False on a missing value, so the `or 0` branches are only type guards.
    if metric == "temperature":
        return float(reading.temperature_c or 0.0)
    if metric == "humidity":
        return float(reading.humidity_pct or 0.0)
    return float(reading.gas_level or 0)
