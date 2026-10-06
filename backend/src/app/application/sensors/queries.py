from datetime import datetime

from app.application.ports.unit_of_work import UnitOfWork
from app.application.sensors.dtos import BucketOutput, DeviceOutput, ReadingOutput

MAX_RAW_READINGS = 2000


class GetReadings:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        device_id: str,
        since: datetime,
        until: datetime,
        bucket_seconds: int | None,
        limit: int = MAX_RAW_READINGS,
    ) -> list[ReadingOutput] | list[BucketOutput]:
        async with self._uow as uow:
            if bucket_seconds is None:
                rows = await uow.readings.list(device_id, since, until, limit)
                return [ReadingOutput.from_entity(r) for r in rows]
            buckets = await uow.readings.aggregate(device_id, since, until, bucket_seconds)
            return [BucketOutput.from_bucket(b) for b in buckets]


class GetLatestReadings:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self) -> list[ReadingOutput]:
        async with self._uow as uow:
            return [ReadingOutput.from_entity(r) for r in await uow.readings.latest()]


class ListDevices:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self) -> list[DeviceOutput]:
        async with self._uow as uow:
            return [DeviceOutput.from_summary(d) for d in await uow.readings.devices()]
