from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.domain.sensor_reading import DeviceSummary, ReadingBucket, SensorReading
from app.domain.user import User


class UserRepository(ABC):
    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def add(self, user: User) -> None: ...


class SensorReadingRepository(ABC):
    @abstractmethod
    async def add(self, reading: SensorReading) -> None: ...

    @abstractmethod
    async def list(
        self, device_id: str, since: datetime, until: datetime, limit: int
    ) -> list[SensorReading]:
        """Readings of one device in [since, until], oldest first, at most `limit`."""

    @abstractmethod
    async def latest(self) -> list[SensorReading]:
        """The most recent reading of every device."""

    @abstractmethod
    async def devices(self) -> list[DeviceSummary]: ...

    @abstractmethod
    async def aggregate(
        self, device_id: str, since: datetime, until: datetime, bucket_seconds: int
    ) -> list[ReadingBucket]:
        """Per-bucket averages, extremes and alert counts, oldest bucket first."""
