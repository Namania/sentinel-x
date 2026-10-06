from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.repositories import SensorReadingRepository, UserRepository
from app.domain.sensor_reading import DeviceSummary, ReadingBucket, SensorReading
from app.domain.user import User
from app.infrastructure.db.models import SensorReadingModel, UserModel


def _to_entity(row: UserModel) -> User:
    return User(
        id=row.id, email=row.email, password_hash=row.password_hash, created_at=row.created_at
    )


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        row = await self._session.get(UserModel, user_id)
        return _to_entity(row) if row is not None else None

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(UserModel).where(UserModel.email == email))
        row = result.scalar_one_or_none()
        return _to_entity(row) if row is not None else None

    async def add(self, user: User) -> None:
        self._session.add(
            UserModel(
                id=user.id,
                email=user.email,
                password_hash=user.password_hash,
                created_at=user.created_at,
            )
        )


def _reading_to_entity(row: SensorReadingModel) -> SensorReading:
    return SensorReading(
        id=row.id,
        device_id=row.device_id,
        recorded_at=row.recorded_at,
        temperature_c=row.temperature_c,
        humidity_pct=row.humidity_pct,
        gas_level=row.gas_level,
        gas_alert=row.gas_alert,
    )


def _float(value: object) -> float | None:
    return None if value is None else float(value)  # asyncpg returns Decimal for avg()


class SqlAlchemySensorReadingRepository(SensorReadingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, reading: SensorReading) -> None:
        self._session.add(
            SensorReadingModel(
                id=reading.id,
                device_id=reading.device_id,
                recorded_at=reading.recorded_at,
                temperature_c=reading.temperature_c,
                humidity_pct=reading.humidity_pct,
                gas_level=reading.gas_level,
                gas_alert=reading.gas_alert,
            )
        )

    async def list(
        self, device_id: str, since: datetime, until: datetime, limit: int
    ) -> list[SensorReading]:
        m = SensorReadingModel
        # Newest readings win when the window holds more than `limit`; returned oldest first.
        stmt = (
            select(m)
            .where(m.device_id == device_id, m.recorded_at >= since, m.recorded_at <= until)
            .order_by(m.recorded_at.desc(), m.id.desc())
            .limit(limit)
        )
        rows = (await self._session.scalars(stmt)).all()
        return [_reading_to_entity(row) for row in reversed(rows)]

    async def latest(self) -> list[SensorReading]:
        m = SensorReadingModel
        rank = (
            func.row_number()
            .over(partition_by=m.device_id, order_by=(m.recorded_at.desc(), m.id.desc()))
            .label("rank")
        )
        ranked = select(m, rank).subquery()
        aliased_model = aliased(m, ranked)
        stmt = select(aliased_model).where(ranked.c.rank == 1).order_by(ranked.c.device_id)
        return [_reading_to_entity(row) for row in (await self._session.scalars(stmt)).all()]

    async def devices(self) -> list[DeviceSummary]:
        m = SensorReadingModel
        stmt = (
            select(m.device_id, func.max(m.recorded_at)).group_by(m.device_id).order_by(m.device_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return [DeviceSummary(device_id=device, last_seen=seen) for device, seen in rows]

    async def aggregate(
        self, device_id: str, since: datetime, until: datetime, bucket_seconds: int
    ) -> list[ReadingBucket]:
        m = SensorReadingModel
        epoch = func.extract("epoch", m.recorded_at)
        bucket = func.to_timestamp(func.floor(epoch / bucket_seconds) * bucket_seconds).label(
            "bucket_start"
        )
        stmt = (
            select(
                bucket,
                func.count().label("count"),
                func.avg(m.temperature_c),
                func.min(m.temperature_c),
                func.max(m.temperature_c),
                func.avg(m.humidity_pct),
                func.min(m.humidity_pct),
                func.max(m.humidity_pct),
                func.avg(m.gas_level),
                func.min(m.gas_level),
                func.max(m.gas_level),
                func.sum(case((m.gas_alert, 1), else_=0)),
            )
            .where(m.device_id == device_id, m.recorded_at >= since, m.recorded_at <= until)
            .group_by(bucket)
            .order_by(bucket)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            ReadingBucket(
                bucket_start=row[0],
                count=row[1],
                temperature_avg=_float(row[2]),
                temperature_min=_float(row[3]),
                temperature_max=_float(row[4]),
                humidity_avg=_float(row[5]),
                humidity_min=_float(row[6]),
                humidity_max=_float(row[7]),
                gas_avg=_float(row[8]),
                gas_min=row[9],
                gas_max=row[10],
                gas_alerts=int(row[11] or 0),
            )
            for row in rows
        ]
