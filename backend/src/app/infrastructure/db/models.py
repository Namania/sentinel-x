from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SensorReadingModel(Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (Index("ix_sensor_readings_device_time", "device_id", "recorded_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    gas_ppm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gas_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
