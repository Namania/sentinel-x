from collections.abc import Callable
from datetime import UTC, datetime

from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.ports.unit_of_work import UnitOfWork
from app.application.sensors.dtos import ReadingInput, ReadingOutput
from app.domain.sensor_reading import SensorReading


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RecordReading:
    """Store one reading from a device and push it to the connected clients."""

    def __init__(
        self,
        uow: UnitOfWork,
        broadcaster: EventBroadcaster,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow = uow
        self._broadcaster = broadcaster
        self._clock = clock or _utc_now

    async def execute(self, data: ReadingInput) -> ReadingOutput:
        reading = SensorReading.create(
            device_id=data.device_id,
            recorded_at=data.recorded_at or self._clock(),
            temperature_c=data.temperature_c,
            humidity_pct=data.humidity_pct,
            gas_ppm=data.gas_ppm,
            gas_alert=data.gas_alert,
        )
        async with self._uow as uow:
            await uow.readings.add(reading)
            await uow.commit()
        output = ReadingOutput.from_entity(reading)
        await self._broadcaster.broadcast({"type": "sensor.reading", "data": output.to_event()})
        return output
