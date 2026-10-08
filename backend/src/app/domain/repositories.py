from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Literal
from uuid import UUID

from app.domain.alert import Alert, Metric
from app.domain.sensor_reading import DeviceSummary, ReadingBucket, SensorReading
from app.domain.ssh_event import SshEvent, SshEventFilter
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


AlertStatus = Literal["open", "resolved", "all"]


class AlertRepository(ABC):
    @abstractmethod
    async def add(self, alert: Alert) -> None: ...

    @abstractmethod
    async def save(self, alert: Alert) -> None:
        """Persist the new state of an existing alert (peak, resolution)."""

    @abstractmethod
    async def open_for(self, device_id: str, metric: Metric) -> Alert | None: ...

    @abstractmethod
    async def get(self, alert_id: UUID) -> Alert | None: ...

    @abstractmethod
    async def latest_for(self, device_id: str, metric: Metric) -> Alert | None:
        """The open alert of that device and metric, else its most recently opened one."""

    @abstractmethod
    async def open_for_device(self, device_id: str) -> dict[Metric, Alert]:
        """Every open alert of one device, keyed by metric (one query per reading)."""

    @abstractmethod
    async def list(self, status: AlertStatus, device_id: str | None, limit: int) -> list[Alert]:
        """Open alerts first, then by opened_at descending; at most `limit`."""

    @abstractmethod
    async def count_open(self) -> int: ...


class SshEventRepository(ABC):
    @abstractmethod
    async def add(self, event: SshEvent) -> bool:
        """Store the event; False (and nothing written) when its journal_id is already known."""

    @abstractmethod
    async def list(self, outcome: SshEventFilter, limit: int) -> list[SshEvent]:
        """Newest first (occurred_at descending), at most `limit`."""
