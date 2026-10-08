from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType

from app.domain.repositories import (
    AlertRepository,
    SensorReadingRepository,
    SshEventRepository,
    UserRepository,
)


class UnitOfWork(ABC):
    users: UserRepository
    readings: SensorReadingRepository
    alerts: AlertRepository
    ssh_events: SshEventRepository

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...
