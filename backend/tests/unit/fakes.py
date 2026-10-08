from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

from app.application.ports.event_broadcaster import Event
from app.application.ports.token_service import InvalidToken, TokenPayload
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.alert import Alert, Metric
from app.domain.repositories import (
    AlertRepository,
    SensorReadingRepository,
    SshEventRepository,
    UserRepository,
)
from app.domain.sensor_reading import DeviceSummary, ReadingBucket, SensorReading
from app.domain.ssh_event import SshEvent
from app.domain.user import User


class InMemoryUserRepository(UserRepository):
    def __init__(self) -> None:
        self._users: dict[UUID, User] = {}

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    async def add(self, user: User) -> None:
        self._users[user.id] = user


class InMemorySensorReadingRepository(SensorReadingRepository):
    def __init__(self) -> None:
        self.readings: list[SensorReading] = []

    async def add(self, reading: SensorReading) -> None:
        self.readings.append(reading)

    async def list(self, device_id, since, until, limit):
        rows = [
            r for r in self.readings if r.device_id == device_id and since <= r.recorded_at <= until
        ]
        ordered = sorted(rows, key=lambda r: r.recorded_at)
        return ordered[-limit:] if limit else ordered

    async def latest(self):
        by_device: dict[str, SensorReading] = {}
        for r in sorted(self.readings, key=lambda r: r.recorded_at):
            by_device[r.device_id] = r
        return list(by_device.values())

    async def devices(self):
        return [
            DeviceSummary(device_id=r.device_id, last_seen=r.recorded_at)
            for r in sorted(await self.latest(), key=lambda r: r.device_id)
        ]

    async def aggregate(self, device_id, since, until, bucket_seconds):
        groups: dict[datetime, list[SensorReading]] = {}
        for r in await self.list(device_id, since, until, limit=10_000):
            start = datetime.fromtimestamp(
                (r.recorded_at.timestamp() // bucket_seconds) * bucket_seconds,
                tz=r.recorded_at.tzinfo,
            )
            groups.setdefault(start, []).append(r)

        def stats(values):
            values = [v for v in values if v is not None]
            if not values:
                return (None, None, None)
            return (sum(values) / len(values), min(values), max(values))

        buckets = []
        for start in sorted(groups):
            rows = groups[start]
            t = stats([r.temperature_c for r in rows])
            h = stats([r.humidity_pct for r in rows])
            g = stats([r.gas_level for r in rows])
            buckets.append(
                ReadingBucket(
                    bucket_start=start,
                    count=len(rows),
                    temperature_avg=t[0],
                    temperature_min=t[1],
                    temperature_max=t[2],
                    humidity_avg=h[0],
                    humidity_min=h[1],
                    humidity_max=h[2],
                    gas_avg=g[0],
                    gas_min=g[1],
                    gas_max=g[2],
                    gas_alerts=sum(1 for r in rows if r.gas_alert),
                )
            )
        return buckets


class InMemoryAlertRepository(AlertRepository):
    def __init__(self) -> None:
        self.alerts: list[Alert] = []
        self.lookups = 0  # open_for / open_for_device calls, to keep the use case to one query

    async def add(self, alert: Alert) -> None:
        self.alerts.append(alert)

    async def save(self, alert: Alert) -> None:
        self.alerts = [alert if a.id == alert.id else a for a in self.alerts]

    async def open_for_device(self, device_id: str) -> dict[Metric, Alert]:
        self.lookups += 1
        return {a.metric: a for a in self.alerts if a.device_id == device_id and a.is_open}

    async def get(self, alert_id: UUID) -> Alert | None:
        return next((a for a in self.alerts if a.id == alert_id), None)

    async def latest_for(self, device_id: str, metric: Metric) -> Alert | None:
        rows = [a for a in self.alerts if a.device_id == device_id and a.metric == metric]
        rows.sort(key=lambda a: (not a.is_open, -a.opened_at.timestamp()))
        return rows[0] if rows else None

    async def open_for(self, device_id: str, metric: Metric) -> Alert | None:
        self.lookups += 1
        return next(
            (
                a
                for a in self.alerts
                if a.device_id == device_id and a.metric == metric and a.is_open
            ),
            None,
        )

    async def list(self, status, device_id, limit):
        rows = [
            a
            for a in self.alerts
            if (device_id is None or a.device_id == device_id)
            and (status == "all" or (status == "open") == a.is_open)
        ]
        rows.sort(key=lambda a: (not a.is_open, -a.opened_at.timestamp()))
        return rows[:limit]

    async def count_open(self) -> int:
        return sum(1 for a in self.alerts if a.is_open)


class InMemorySshEventRepository(SshEventRepository):
    def __init__(self) -> None:
        self.events: list[SshEvent] = []

    async def add(self, event: SshEvent) -> bool:
        if any(e.journal_id == event.journal_id for e in self.events):
            return False
        self.events.append(event)
        return True

    async def list(self, outcome, limit):
        rows = [e for e in self.events if outcome == "all" or e.outcome == outcome]
        rows.sort(key=lambda e: e.occurred_at, reverse=True)
        return rows[:limit]


class InMemoryUnitOfWork(UnitOfWork):
    def __init__(self) -> None:
        self.users = InMemoryUserRepository()
        self.readings = InMemorySensorReadingRepository()
        self.alerts = InMemoryAlertRepository()
        self.ssh_events = InMemorySshEventRepository()
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakePasswordHasher:
    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed:{password}"


class FakeTokenService:
    def issue_access(self, user_id: UUID) -> str:
        return f"access:{user_id}"

    def issue_refresh(self, user_id: UUID) -> str:
        return f"refresh:{user_id}"

    def decode(self, token: str) -> TokenPayload:
        try:
            kind, raw_id = token.split(":", 1)
            return TokenPayload(user_id=UUID(raw_id), type=kind)
        except ValueError as exc:
            raise InvalidToken() from exc


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.broadcasts: list[Event] = []
        self.direct: list[tuple[UUID, Event]] = []

    async def broadcast(self, event: Event) -> None:
        self.broadcasts.append(event)

    async def send_to_user(self, user_id: UUID, event: Event) -> None:
        self.direct.append((user_id, event))


MJPEG_BOUNDARY = "123456789000000000000987654321"


def mjpeg_part(payload: bytes, boundary: str = MJPEG_BOUNDARY) -> bytes:
    return (
        f"\r\n--{boundary}\r\n".encode()
        + f"Content-Type: image/jpeg\r\nContent-Length: {len(payload)}\r\n\r\n".encode()
        + payload
    )


class FakeCamera:
    """Scriptable MJPEG upstream: the test pushes frames or failures, the relay reads them."""

    def __init__(self) -> None:
        self.content_type = f"multipart/x-mixed-replace;boundary={MJPEG_BOUNDARY}"
        self._chunks: asyncio.Queue[bytes | Exception | None] = asyncio.Queue()
        self.opens = 0
        self.closes = 0

    def push_frame(self, payload: bytes) -> None:
        self._chunks.put_nowait(mjpeg_part(payload))

    def fail(self, error: Exception | None = None) -> None:
        self._chunks.put_nowait(error or ConnectionError("camera lost"))

    @asynccontextmanager
    async def open(self) -> AsyncIterator[FakeCamera]:
        self.opens += 1
        try:
            yield self
        finally:
            self.closes += 1

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        while True:
            item = await self._chunks.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item
