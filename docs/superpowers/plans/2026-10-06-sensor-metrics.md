# Sensor Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest temperature / humidity / gas readings from the indoor ESP32 over an HTTP route protected by a device key, store them in Postgres, serve history (raw or bucketed) over REST, push each new reading on the existing WebSocket, and chart them live inside the Dashboard.

**Architecture:** Clean architecture as in the rest of `backend/`: a `SensorReading` entity and repository interface in `domain`, `RecordReading` / `GetReadings` / `GetLatestReadings` / `ListDevices` use cases in `application`, SQLAlchemy model + repository + Alembic migration in `infrastructure`, FastAPI router + device-key dependency in `presentation`. The use case broadcasts `sensor.reading` through the existing `ConnectionHub`, so the WebSocket needs no change. The front adds a `features/metrics` module (API types, two hooks, tiles, four Recharts charts, table, filters) rendered by the Dashboard page.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, pydantic, httpx; React 19, shadcn/ui `chart` (Recharts 3.8), `select`, `switch`, `table`, `toggle-group` (already added to `frontend/`), MSW 3 (`http` and `ws`), Vitest.

**Spec:** `docs/superpowers/specs/2026-10-06-sensor-metrics-design.md`

## Global Constraints

- Backend commands run from `backend/` with `uv run …`; integration tests need the compose `db` service (`sentinel_test` database). Front commands run from `frontend/` with pnpm; run `pnpm format` before `pnpm lint`.
- `domain` and `application` never import FastAPI, SQLAlchemy, pydantic or httpx.
- Ingestion contract (exact JSON keys): `device_id`, optional `recorded_at`, optional `gaz { mostGaz, quantity }`, optional `temperature { humidity, temp }`. Bounds: `device_id` matches `^[a-z0-9-]{1,64}$`; `temp` in [-40, 125]; `humidity` in [0, 100]; `quantity` integer ≥ 0. Out of bounds → 422. Missing `recorded_at` → server time (UTC).
- Flat output shape everywhere (REST, WebSocket event `data`): `id, device_id, recorded_at, temperature_c, humidity_pct, gas_ppm, gas_alert`. WebSocket event: `{"type": "sensor.reading", "data": {…}}`.
- Routes: `POST /sensors/readings` (header `X-Device-Key`), `GET /sensors/readings?device_id&from&to&bucket`, `GET /sensors/latest`, `GET /sensors/devices`. `bucket` ∈ `1m, 5m, 15m, 1h`; raw results capped at 2000; `from` defaults to now − 1 h, `to` to now.
- Setting `DEVICE_API_KEY`: optional; when set it must be at least 16 characters (startup error otherwise); unset → `POST /sensors/readings` answers 503; wrong/missing header → 401.
- Front ranges and buckets: `15m` → raw, `1h` → `1m`, `6h` → `5m`, `24h` → `15m`.
- Metric colors (validated with the dataviz palette script, light surface `#ffffff`, dark `#252525`): temperature `#d9541e` / `#e8622f`, humidity `#2b6fd6` / `#4b8ae6`, gas `#0f8f6a` / `#2aa87f`, exposed as CSS variables `--metric-temperature`, `--metric-humidity`, `--metric-gas`. One metric per chart, one y-axis, no legend for a single series, text in theme text colors, alert state uses `--destructive` with an icon and a label.
- French copy: « Mesures », « Température », « Humidité », « Gaz », « Alerte gaz », « Direct », « Graphiques », « Tableau », « Appareil », « Plage », « 15 min », « 1 h », « 6 h », « 24 h », « Aucune mesure pour cet appareil sur la plage choisie. ».
- Commit after every task with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; before each front commit run `pnpm format && pnpm lint && pnpm typecheck && pnpm test && pnpm build`.

## Review Focus

1. A reading whose `recorded_at` has no timezone, or a `from`/`to` query without one, must be treated as UTC rather than crash or be compared with aware datetimes. → Tests in Task 1 (entity) and Task 4 (route).
2. A body with neither `gaz` nor `temperature` is a valid heartbeat and must be stored with null metrics, not rejected. → Test in Task 4.
3. An empty bucket range (no readings) must return `[]`, and buckets with no gas readings must have `gas_avg = null`, not `0`. → Tests in Task 2.
4. The WebSocket client of the front must not loop at full speed when the server is down: reconnection waits grow 1 s → 30 s and stop on unmount. → Test in Task 6.
5. Live readings for another device must not pollute the selected device's series or tiles. → Test in Task 7.

---

### Task 1: Domain — `SensorReading`, buckets, repository interface

**Files:**
- Create: `backend/src/app/domain/sensor_reading.py`
- Modify: `backend/src/app/domain/errors.py`, `backend/src/app/domain/repositories.py`
- Test: `backend/tests/unit/test_sensor_reading.py`

**Interfaces:**
- Produces: `SensorReading.create(*, device_id, recorded_at, temperature_c, humidity_pct, gas_ppm, gas_alert) -> SensorReading`; `ReadingBucket`, `DeviceSummary` dataclasses; `InvalidReading(DomainError)`; `SensorReadingRepository` with `add`, `list(device_id, since, until, limit)`, `latest()`, `devices()`, `aggregate(device_id, since, until, bucket_seconds)`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_sensor_reading.py`:

```python
from datetime import UTC, datetime, timezone, timedelta

import pytest

from app.domain.errors import InvalidReading
from app.domain.sensor_reading import SensorReading

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def make(**overrides):
    data = dict(
        device_id="esp-interieur",
        recorded_at=NOW,
        temperature_c=22.5,
        humidity_pct=48.0,
        gas_ppm=410,
        gas_alert=False,
    )
    data.update(overrides)
    return SensorReading.create(**data)


def test_creates_a_reading_with_an_id_and_utc_time():
    reading = make()
    assert reading.id is not None
    assert reading.recorded_at == NOW
    assert reading.device_id == "esp-interieur"


def test_converts_recorded_at_to_utc():
    paris = timezone(timedelta(hours=2))
    reading = make(recorded_at=datetime(2026, 10, 6, 11, 0, tzinfo=paris))
    assert reading.recorded_at == NOW


def test_naive_recorded_at_is_taken_as_utc():
    reading = make(recorded_at=datetime(2026, 10, 6, 9, 0))
    assert reading.recorded_at == NOW


def test_metrics_may_all_be_missing():
    reading = make(temperature_c=None, humidity_pct=None, gas_ppm=None)
    assert (reading.temperature_c, reading.humidity_pct, reading.gas_ppm) == (None, None, None)


@pytest.mark.parametrize("device_id", ["", "ESP", "esp interieur", "a" * 65, "esp_1"])
def test_rejects_bad_device_ids(device_id):
    with pytest.raises(InvalidReading):
        make(device_id=device_id)


@pytest.mark.parametrize(
    "field, value",
    [("temperature_c", -40.1), ("temperature_c", 125.1), ("humidity_pct", -0.1),
     ("humidity_pct", 100.1), ("gas_ppm", -1)],
)
def test_rejects_out_of_range_values(field, value):
    with pytest.raises(InvalidReading):
        make(**{field: value})


def test_accepts_boundary_values():
    reading = make(temperature_c=-40, humidity_pct=100, gas_ppm=0)
    assert reading.temperature_c == -40
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_sensor_reading.py -q`
Expected: collection error — `ModuleNotFoundError: app.domain.sensor_reading`.

- [ ] **Step 3: Implement**

Append to `backend/src/app/domain/errors.py`:

```python
class InvalidReading(DomainError):
    """A sensor reading violates the accepted bounds."""
```

`backend/src/app/domain/sensor_reading.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.errors import InvalidReading

DEVICE_ID_PATTERN = re.compile(r"^[a-z0-9-]{1,64}$")
TEMPERATURE_RANGE = (-40.0, 125.0)
HUMIDITY_RANGE = (0.0, 100.0)


def _check_range(name: str, value: float | None, bounds: tuple[float, float]) -> None:
    if value is None:
        return
    low, high = bounds
    if not low <= value <= high:
        raise InvalidReading(f"{name} must be between {low:g} and {high:g}")


def _to_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SensorReading:
    """One message from a device: the metrics it carried at one instant."""

    id: UUID
    device_id: str
    recorded_at: datetime
    temperature_c: float | None
    humidity_pct: float | None
    gas_ppm: int | None
    gas_alert: bool

    @classmethod
    def create(
        cls,
        *,
        device_id: str,
        recorded_at: datetime,
        temperature_c: float | None,
        humidity_pct: float | None,
        gas_ppm: int | None,
        gas_alert: bool,
    ) -> SensorReading:
        if not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise InvalidReading("device_id must match [a-z0-9-]{1,64}")
        _check_range("temperature_c", temperature_c, TEMPERATURE_RANGE)
        _check_range("humidity_pct", humidity_pct, HUMIDITY_RANGE)
        if gas_ppm is not None and gas_ppm < 0:
            raise InvalidReading("gas_ppm must be positive")
        return cls(
            id=uuid4(),
            device_id=device_id,
            recorded_at=_to_utc(recorded_at),
            temperature_c=temperature_c,
            humidity_pct=humidity_pct,
            gas_ppm=gas_ppm,
            gas_alert=gas_alert,
        )


@dataclass(frozen=True, slots=True)
class ReadingBucket:
    """Aggregate of the readings of one device over one time bucket."""

    bucket_start: datetime
    count: int
    temperature_avg: float | None
    temperature_min: float | None
    temperature_max: float | None
    humidity_avg: float | None
    humidity_min: float | None
    humidity_max: float | None
    gas_avg: float | None
    gas_min: int | None
    gas_max: int | None
    gas_alerts: int


@dataclass(frozen=True, slots=True)
class DeviceSummary:
    device_id: str
    last_seen: datetime
```

Append to `backend/src/app/domain/repositories.py` (add `from datetime import datetime` and the import of the three new classes at the top):

```python
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
```

- [ ] **Step 4: Run the tests, then lint, then commit**

Run: `uv run pytest tests/unit/test_sensor_reading.py -q` → 12 passed. Then `uv run ruff check . && uv run ruff format .`.

```bash
cd /Users/namania/git/sentinel-x
git add backend/src/app/domain backend/tests/unit/test_sensor_reading.py
git commit -m "feat(backend): SensorReading entity, buckets and repository interface

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Infrastructure — table, migration, SQL repository, unit of work

**Files:**
- Modify: `backend/src/app/infrastructure/db/models.py`, `backend/src/app/infrastructure/db/repositories.py`, `backend/src/app/infrastructure/db/unit_of_work.py`, `backend/src/app/application/ports/unit_of_work.py`, `backend/tests/unit/fakes.py`
- Create: `backend/alembic/versions/0002_create_sensor_readings.py`
- Test: `backend/tests/integration/test_sensor_reading_repository.py`

**Interfaces:**
- Consumes: Task 1 classes.
- Produces: `SensorReadingModel`, `SqlAlchemySensorReadingRepository(session)`, `UnitOfWork.readings`, test fake `InMemorySensorReadingRepository` wired into `InMemoryUnitOfWork.readings`.

- [ ] **Step 1: Write the failing integration tests**

`backend/tests/integration/test_sensor_reading_repository.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.sensor_reading import SensorReading
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def reading(device="esp-interieur", minutes=0, temp=20.0, hum=50.0, gas=400, alert=False):
    return SensorReading.create(
        device_id=device,
        recorded_at=T0 + timedelta(minutes=minutes),
        temperature_c=temp,
        humidity_pct=hum,
        gas_ppm=gas,
        gas_alert=alert,
    )


@pytest.fixture
async def uow(session_factory):
    return SqlAlchemyUnitOfWork(session_factory)


async def seed(uow, readings):
    async with uow as tx:
        for r in readings:
            await tx.readings.add(r)
        await tx.commit()


async def test_lists_readings_of_one_device_in_order(uow):
    await seed(uow, [reading(minutes=2), reading(minutes=0), reading(device="esp-ext", minutes=1)])
    async with uow as tx:
        rows = await tx.readings.list("esp-interieur", T0, T0 + timedelta(hours=1), limit=10)
    assert [r.recorded_at for r in rows] == [T0, T0 + timedelta(minutes=2)]


async def test_list_respects_limit_and_window(uow):
    await seed(uow, [reading(minutes=m) for m in range(5)])
    async with uow as tx:
        rows = await tx.readings.list("esp-interieur", T0 + timedelta(minutes=1), T0 + timedelta(minutes=3), limit=2)
    assert [r.recorded_at.minute for r in rows] == [1, 2]


async def test_latest_returns_one_reading_per_device(uow):
    await seed(uow, [reading(minutes=0, temp=20), reading(minutes=5, temp=21), reading(device="esp-ext", temp=10)])
    async with uow as tx:
        rows = await tx.readings.latest()
    assert {(r.device_id, r.temperature_c) for r in rows} == {("esp-interieur", 21.0), ("esp-ext", 10.0)}


async def test_devices_with_last_seen(uow):
    await seed(uow, [reading(minutes=0), reading(minutes=7), reading(device="esp-ext", minutes=3)])
    async with uow as tx:
        devices = await tx.readings.devices()
    assert [(d.device_id, d.last_seen.minute) for d in devices] == [("esp-ext", 3), ("esp-interieur", 7)]


async def test_aggregates_per_bucket(uow):
    await seed(
        uow,
        [
            reading(minutes=0, temp=20, hum=40, gas=400),
            reading(minutes=1, temp=22, hum=60, gas=600, alert=True),
            reading(minutes=6, temp=30, hum=50, gas=None),
        ],
    )
    async with uow as tx:
        buckets = await tx.readings.aggregate("esp-interieur", T0, T0 + timedelta(minutes=10), 300)
    assert [b.bucket_start for b in buckets] == [T0, T0 + timedelta(minutes=5)]
    first, second = buckets
    assert (first.count, first.temperature_avg, first.temperature_min, first.temperature_max) == (2, 21.0, 20.0, 22.0)
    assert (first.humidity_avg, first.gas_avg, first.gas_min, first.gas_max, first.gas_alerts) == (50.0, 500.0, 400, 600, 1)
    assert (second.count, second.temperature_avg, second.gas_avg, second.gas_alerts) == (1, 30.0, None, 0)


async def test_aggregate_of_an_empty_window_is_empty(uow):
    async with uow as tx:
        assert await tx.readings.aggregate("esp-interieur", T0, T0 + timedelta(hours=1), 60) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/integration/test_sensor_reading_repository.py -q`
Expected: FAIL — `AttributeError: 'SqlAlchemyUnitOfWork' object has no attribute 'readings'`.

- [ ] **Step 3: Implement**

Append to `backend/src/app/infrastructure/db/models.py` (extend the imports: `Boolean, DateTime, Float, Index, Integer, String, Uuid`):

```python
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
```

`backend/alembic/versions/0002_create_sensor_readings.py`:

```python
"""create sensor_readings

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sensor_readings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("humidity_pct", sa.Float(), nullable=True),
        sa.Column("gas_ppm", sa.Integer(), nullable=True),
        sa.Column("gas_alert", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sensor_readings_device_time", "sensor_readings", ["device_id", "recorded_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_sensor_readings_device_time", table_name="sensor_readings")
    op.drop_table("sensor_readings")
```

Append to `backend/src/app/infrastructure/db/repositories.py` (extend imports: `from datetime import datetime`, `from sqlalchemy import case, func, select`, the new domain classes and `SensorReadingModel`):

```python
def _reading_to_entity(row: SensorReadingModel) -> SensorReading:
    return SensorReading(
        id=row.id,
        device_id=row.device_id,
        recorded_at=row.recorded_at,
        temperature_c=row.temperature_c,
        humidity_pct=row.humidity_pct,
        gas_ppm=row.gas_ppm,
        gas_alert=row.gas_alert,
    )


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
                gas_ppm=reading.gas_ppm,
                gas_alert=reading.gas_alert,
            )
        )

    async def list(
        self, device_id: str, since: datetime, until: datetime, limit: int
    ) -> list[SensorReading]:
        m = SensorReadingModel
        stmt = (
            select(m)
            .where(m.device_id == device_id, m.recorded_at >= since, m.recorded_at <= until)
            .order_by(m.recorded_at)
            .limit(limit)
        )
        return [_reading_to_entity(row) for row in (await self._session.scalars(stmt)).all()]

    async def latest(self) -> list[SensorReading]:
        m = SensorReadingModel
        stmt = select(m).distinct(m.device_id).order_by(m.device_id, m.recorded_at.desc())
        return [_reading_to_entity(row) for row in (await self._session.scalars(stmt)).all()]

    async def devices(self) -> list[DeviceSummary]:
        m = SensorReadingModel
        stmt = (
            select(m.device_id, func.max(m.recorded_at))
            .group_by(m.device_id)
            .order_by(m.device_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return [DeviceSummary(device_id=d, last_seen=seen) for d, seen in rows]

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
                func.avg(m.gas_ppm),
                func.min(m.gas_ppm),
                func.max(m.gas_ppm),
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


def _float(value: object) -> float | None:
    return None if value is None else float(value)  # asyncpg returns Decimal for avg()
```

In `backend/src/app/application/ports/unit_of_work.py`, import `SensorReadingRepository` and declare `readings: SensorReadingRepository` next to `users`. In `backend/src/app/infrastructure/db/unit_of_work.py`, import `SqlAlchemySensorReadingRepository` and add in `__aenter__`: `self.readings = SqlAlchemySensorReadingRepository(self._session)`.

Test fake, appended to `backend/tests/unit/fakes.py` (import `datetime`, `DeviceSummary`, `ReadingBucket`, `SensorReading`, `SensorReadingRepository`), and `InMemoryUnitOfWork.__init__` gains `self.readings = InMemorySensorReadingRepository()`:

```python
class InMemorySensorReadingRepository(SensorReadingRepository):
    def __init__(self) -> None:
        self.readings: list[SensorReading] = []

    async def add(self, reading: SensorReading) -> None:
        self.readings.append(reading)

    async def list(self, device_id, since, until, limit):
        rows = [r for r in self.readings if r.device_id == device_id and since <= r.recorded_at <= until]
        return sorted(rows, key=lambda r: r.recorded_at)[:limit]

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
                (r.recorded_at.timestamp() // bucket_seconds) * bucket_seconds, tz=r.recorded_at.tzinfo
            )
            groups.setdefault(start, []).append(r)

        def stats(values):
            values = [v for v in values if v is not None]
            return (sum(values) / len(values), min(values), max(values)) if values else (None, None, None)

        buckets = []
        for start in sorted(groups):
            rows = groups[start]
            t = stats([r.temperature_c for r in rows])
            h = stats([r.humidity_pct for r in rows])
            g = stats([r.gas_ppm for r in rows])
            buckets.append(
                ReadingBucket(
                    bucket_start=start, count=len(rows),
                    temperature_avg=t[0], temperature_min=t[1], temperature_max=t[2],
                    humidity_avg=h[0], humidity_min=h[1], humidity_max=h[2],
                    gas_avg=g[0], gas_min=g[1], gas_max=g[2],
                    gas_alerts=sum(1 for r in rows if r.gas_alert),
                )
            )
        return buckets
```

- [ ] **Step 4: Run the tests, ruff, commit**

Run: `uv run pytest tests/integration/test_sensor_reading_repository.py -q` → 6 passed; `uv run pytest -q` → all green; `uv run ruff check . && uv run ruff format .`.

```bash
cd /Users/namania/git/sentinel-x
git add backend/src backend/alembic backend/tests
git commit -m "feat(backend): sensor_readings table, SQL repository with bucket aggregation

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Application — `RecordReading`, `GetReadings`, `GetLatestReadings`, `ListDevices`

**Files:**
- Create: `backend/src/app/application/sensors/__init__.py`, `backend/src/app/application/sensors/dtos.py`, `backend/src/app/application/sensors/record.py`, `backend/src/app/application/sensors/queries.py`
- Test: `backend/tests/unit/test_record_reading.py`, `backend/tests/unit/test_sensor_queries.py`

**Interfaces:**
- Consumes: `UnitOfWork.readings`, `EventBroadcaster.broadcast`.
- Produces: `ReadingInput`, `ReadingOutput.from_entity()/to_event()`, `BucketOutput.from_bucket()`, `DeviceOutput`; `RecordReading(uow, broadcaster, clock=None).execute(ReadingInput) -> ReadingOutput`; `GetReadings(uow).execute(device_id, since, until, bucket_seconds, limit=2000)`; `GetLatestReadings(uow).execute()`; `ListDevices(uow).execute()`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_record_reading.py`:

```python
from datetime import UTC, datetime

import pytest

from app.application.sensors.dtos import ReadingInput
from app.application.sensors.record import RecordReading
from app.domain.errors import InvalidReading
from tests.unit.fakes import InMemoryUnitOfWork

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.events = []

    async def broadcast(self, event):
        self.events.append(event)

    async def send_to_user(self, user_id, event):
        self.events.append(event)


def make_input(**overrides):
    data = dict(device_id="esp-interieur", recorded_at=None, temperature_c=22.5,
                humidity_pct=48.0, gas_ppm=410, gas_alert=False)
    data.update(overrides)
    return ReadingInput(**data)


async def test_stores_the_reading_and_broadcasts_it():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    output = await RecordReading(uow, bus, clock=lambda: NOW).execute(make_input())
    assert uow.committed
    assert [r.id for r in uow.readings.readings] == [output.id]
    assert output.recorded_at == NOW  # server time when the device sends none
    assert bus.events == [{"type": "sensor.reading", "data": output.to_event()}]
    assert bus.events[0]["data"]["recorded_at"] == "2026-10-06T09:00:00+00:00"
    assert bus.events[0]["data"]["id"] == str(output.id)


async def test_keeps_the_device_timestamp_when_given():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    sent_at = datetime(2026, 10, 6, 8, 59, tzinfo=UTC)
    output = await RecordReading(uow, bus, clock=lambda: NOW).execute(make_input(recorded_at=sent_at))
    assert output.recorded_at == sent_at


async def test_invalid_values_are_rejected_before_storage():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    with pytest.raises(InvalidReading):
        await RecordReading(uow, bus).execute(make_input(humidity_pct=101))
    assert uow.readings.readings == [] and bus.events == []
```

`backend/tests/unit/test_sensor_queries.py`:

```python
from datetime import UTC, datetime, timedelta

from app.application.sensors.dtos import BucketOutput, ReadingOutput
from app.application.sensors.queries import GetLatestReadings, GetReadings, ListDevices
from app.domain.sensor_reading import SensorReading
from tests.unit.fakes import InMemoryUnitOfWork

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def seeded():
    uow = InMemoryUnitOfWork()
    for device, minutes, temp in [("esp-interieur", 0, 20.0), ("esp-interieur", 3, 24.0), ("esp-ext", 1, 10.0)]:
        uow.readings.readings.append(
            SensorReading.create(device_id=device, recorded_at=T0 + timedelta(minutes=minutes),
                                 temperature_c=temp, humidity_pct=50.0, gas_ppm=400, gas_alert=False)
        )
    return uow


async def test_raw_readings_when_no_bucket():
    rows = await GetReadings(seeded()).execute("esp-interieur", T0, T0 + timedelta(hours=1), None)
    assert all(isinstance(r, ReadingOutput) for r in rows)
    assert [r.temperature_c for r in rows] == [20.0, 24.0]


async def test_buckets_when_a_bucket_size_is_given():
    rows = await GetReadings(seeded()).execute("esp-interieur", T0, T0 + timedelta(hours=1), 300)
    assert len(rows) == 1 and isinstance(rows[0], BucketOutput)
    assert rows[0].temperature_avg == 22.0 and rows[0].count == 2


async def test_latest_and_devices():
    uow = seeded()
    latest = await GetLatestReadings(uow).execute()
    assert {(r.device_id, r.temperature_c) for r in latest} == {("esp-interieur", 24.0), ("esp-ext", 10.0)}
    devices = await ListDevices(uow).execute()
    assert [d.device_id for d in devices] == ["esp-ext", "esp-interieur"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_record_reading.py tests/unit/test_sensor_queries.py -q`
Expected: collection errors — `app.application.sensors` missing.

- [ ] **Step 3: Implement**

`backend/src/app/application/sensors/__init__.py`: empty.

`backend/src/app/application/sensors/dtos.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.sensor_reading import DeviceSummary, ReadingBucket, SensorReading


@dataclass(frozen=True, slots=True)
class ReadingInput:
    device_id: str
    recorded_at: datetime | None
    temperature_c: float | None
    humidity_pct: float | None
    gas_ppm: int | None
    gas_alert: bool


@dataclass(frozen=True, slots=True)
class ReadingOutput:
    id: UUID
    device_id: str
    recorded_at: datetime
    temperature_c: float | None
    humidity_pct: float | None
    gas_ppm: int | None
    gas_alert: bool

    @classmethod
    def from_entity(cls, reading: SensorReading) -> ReadingOutput:
        return cls(
            id=reading.id,
            device_id=reading.device_id,
            recorded_at=reading.recorded_at,
            temperature_c=reading.temperature_c,
            humidity_pct=reading.humidity_pct,
            gas_ppm=reading.gas_ppm,
            gas_alert=reading.gas_alert,
        )

    def to_event(self) -> dict[str, Any]:
        """JSON-safe payload for the WebSocket event."""
        data = asdict(self)
        data["id"] = str(self.id)
        data["recorded_at"] = self.recorded_at.isoformat()
        return data


@dataclass(frozen=True, slots=True)
class BucketOutput:
    bucket_start: datetime
    count: int
    temperature_avg: float | None
    temperature_min: float | None
    temperature_max: float | None
    humidity_avg: float | None
    humidity_min: float | None
    humidity_max: float | None
    gas_avg: float | None
    gas_min: int | None
    gas_max: int | None
    gas_alerts: int

    @classmethod
    def from_bucket(cls, bucket: ReadingBucket) -> BucketOutput:
        return cls(**asdict(bucket))


@dataclass(frozen=True, slots=True)
class DeviceOutput:
    device_id: str
    last_seen: datetime

    @classmethod
    def from_summary(cls, summary: DeviceSummary) -> DeviceOutput:
        return cls(device_id=summary.device_id, last_seen=summary.last_seen)
```

`backend/src/app/application/sensors/record.py`:

```python
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
```

`backend/src/app/application/sensors/queries.py`:

```python
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
```

- [ ] **Step 4: Run the tests, ruff, commit**

Run: `uv run pytest tests/unit -q` → all green (6 new). `uv run ruff check . && uv run ruff format .`. Also confirm the layering: `grep -rE "fastapi|sqlalchemy|pydantic|httpx" src/app/domain src/app/application` prints nothing.

```bash
cd /Users/namania/git/sentinel-x
git add backend/src/app/application backend/tests/unit
git commit -m "feat(backend): RecordReading, GetReadings, GetLatestReadings and ListDevices use cases

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: HTTP routes, device key, WebSocket push

**Files:**
- Create: `backend/src/app/presentation/http/sensors.py`
- Modify: `backend/src/app/infrastructure/config.py`, `backend/src/app/presentation/dependencies.py`, `backend/src/app/presentation/http/errors.py`, `backend/src/app/presentation/main.py`, `backend/.env.example`, `backend/tests/integration/conftest.py`
- Test: `backend/tests/unit/test_settings.py` (append), `backend/tests/integration/test_sensors_http.py`

**Interfaces:**
- Consumes: Task 3 use cases, `HubDep`, `UowDep`, `CurrentUserIdDep`, `SettingsDep`.
- Produces: routes under `/sensors`; `Settings.device_api_key`; `TEST_SETTINGS.device_api_key = "test-device-key-0123456789"` and `DEVICE_HEADERS = {"X-Device-Key": …}` exported by the integration conftest.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_settings.py`:

```python
def test_device_api_key_is_optional_but_must_be_long_when_set():
    assert Settings(_env_file=None, jwt_secret="x" * 32).device_api_key is None
    assert Settings(_env_file=None, jwt_secret="x" * 32, device_api_key="k" * 16).device_api_key == "k" * 16
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="x" * 32, device_api_key="short")
```

In `backend/tests/integration/conftest.py`, add `device_api_key="test-device-key-0123456789",` to `TEST_SETTINGS` and export:

```python
DEVICE_HEADERS = {"X-Device-Key": "test-device-key-0123456789"}
```

`backend/tests/integration/test_sensors_http.py`:

```python
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.presentation.main import create_app
from tests.integration.conftest import DEVICE_HEADERS, TEST_SETTINGS, create_user_and_login

BODY = {
    "device_id": "esp-interieur",
    "gaz": {"mostGaz": False, "quantity": 412},
    "temperature": {"humidity": 48.5, "temp": 22.9},
}


def auth(client):
    return {"Authorization": f"Bearer {create_user_and_login(client)['access_token']}"}


def test_device_posts_a_reading(client):
    response = client.post("/sensors/readings", json=BODY, headers=DEVICE_HEADERS)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["device_id"] == "esp-interieur"
    assert (data["temperature_c"], data["humidity_pct"], data["gas_ppm"], data["gas_alert"]) == (22.9, 48.5, 412, False)
    assert data["recorded_at"].endswith("+00:00") or data["recorded_at"].endswith("Z")


def test_device_timestamp_is_kept_and_naive_times_are_utc(client):
    body = {**BODY, "recorded_at": "2026-10-06T09:00:00"}
    response = client.post("/sensors/readings", json=body, headers=DEVICE_HEADERS)
    assert response.status_code == 201
    assert response.json()["recorded_at"] == "2026-10-06T09:00:00Z"


def test_heartbeat_without_metrics_is_stored(client):
    response = client.post("/sensors/readings", json={"device_id": "esp-interieur"}, headers=DEVICE_HEADERS)
    assert response.status_code == 201
    data = response.json()
    assert (data["temperature_c"], data["humidity_pct"], data["gas_ppm"], data["gas_alert"]) == (None, None, None, False)


def test_post_requires_the_device_key(client):
    assert client.post("/sensors/readings", json=BODY).status_code == 401
    assert client.post("/sensors/readings", json=BODY, headers={"X-Device-Key": "nope"}).status_code == 401


def test_post_rejects_out_of_range_values(client):
    body = {**BODY, "temperature": {"humidity": 101, "temp": 20}}
    response = client.post("/sensors/readings", json=body, headers=DEVICE_HEADERS)
    assert response.status_code == 422


def test_post_is_unavailable_without_a_configured_key():
    settings = TEST_SETTINGS.model_copy(update={"device_api_key": None})
    with TestClient(create_app(settings)) as unconfigured:
        response = unconfigured.post("/sensors/readings", json=BODY, headers=DEVICE_HEADERS)
    assert response.status_code == 503


def test_history_raw_and_bucketed(client):
    headers = auth(client)
    t0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
    for minutes, temp in [(0, 20.0), (1, 22.0), (6, 30.0)]:
        body = {**BODY, "recorded_at": (t0 + timedelta(minutes=minutes)).isoformat(),
                "temperature": {"humidity": 50, "temp": temp}}
        assert client.post("/sensors/readings", json=body, headers=DEVICE_HEADERS).status_code == 201

    raw = client.get(
        "/sensors/readings",
        params={"device_id": "esp-interieur", "from": t0.isoformat(), "to": (t0 + timedelta(minutes=10)).isoformat()},
        headers=headers,
    )
    assert raw.status_code == 200
    assert [r["temperature_c"] for r in raw.json()] == [20.0, 22.0, 30.0]

    buckets = client.get(
        "/sensors/readings",
        params={"device_id": "esp-interieur", "from": "2026-10-06T09:00:00", "to": "2026-10-06T09:10:00", "bucket": "5m"},
        headers=headers,
    )
    assert buckets.status_code == 200
    assert [(b["count"], b["temperature_avg"]) for b in buckets.json()] == [(2, 21.0), (1, 30.0)]
    assert buckets.json()[0]["bucket_start"] == "2026-10-06T09:00:00Z"


def test_history_defaults_to_the_last_hour(client):
    headers = auth(client)
    old = {**BODY, "recorded_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat()}
    assert client.post("/sensors/readings", json=old, headers=DEVICE_HEADERS).status_code == 201
    assert client.post("/sensors/readings", json=BODY, headers=DEVICE_HEADERS).status_code == 201
    response = client.get("/sensors/readings", params={"device_id": "esp-interieur"}, headers=headers)
    assert len(response.json()) == 1


def test_history_rejects_unknown_bucket(client):
    response = client.get("/sensors/readings", params={"device_id": "esp-interieur", "bucket": "2m"}, headers=auth(client))
    assert response.status_code == 422


def test_history_requires_a_user(client):
    assert client.get("/sensors/readings", params={"device_id": "esp-interieur"}).status_code == 401


def test_latest_and_devices(client):
    headers = auth(client)
    client.post("/sensors/readings", json=BODY, headers=DEVICE_HEADERS)
    client.post("/sensors/readings", json={**BODY, "device_id": "esp-ext"}, headers=DEVICE_HEADERS)
    latest = client.get("/sensors/latest", headers=headers).json()
    assert sorted(r["device_id"] for r in latest) == ["esp-ext", "esp-interieur"]
    devices = client.get("/sensors/devices", headers=headers).json()
    assert [d["device_id"] for d in devices] == ["esp-ext", "esp-interieur"]
    assert "last_seen" in devices[0]


def test_new_reading_is_pushed_on_the_websocket(client):
    tokens = create_user_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        response = client.post("/sensors/readings", json=BODY, headers=DEVICE_HEADERS)
        assert response.status_code == 201
        event = ws.receive_json()
    assert event["type"] == "sensor.reading"
    assert event["data"]["id"] == response.json()["id"]
    assert event["data"]["gas_ppm"] == 412
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_settings.py tests/integration/test_sensors_http.py -q`
Expected: settings test fails (`device_api_key` unknown → pydantic ignores extra: the assertion `is None` raises AttributeError), the HTTP tests fail with 404 / ImportError on `DEVICE_HEADERS`.

- [ ] **Step 3: Implement**

`backend/src/app/infrastructure/config.py` — add after `camera_stream_url`:

```python
    # Shared secret the ESP32 devices send in X-Device-Key to post sensor readings.
    device_api_key: str | None = None

    @field_validator("device_api_key")
    @classmethod
    def _device_key_must_be_long(cls, value: str | None) -> str | None:
        if value is not None and len(value) < 16:
            raise ValueError("DEVICE_API_KEY must be at least 16 characters")
        return value
```

`backend/.env.example` — append:

```
# Optional: shared key the ESP32 sends as X-Device-Key on POST /sensors/readings (16+ chars).
DEVICE_API_KEY=
```

`backend/src/app/presentation/dependencies.py` — add (imports: `secrets`, `Header`):

```python
def require_device_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_device_key: Annotated[str | None, Header(alias="X-Device-Key")] = None,
) -> None:
    """Guard for device ingestion routes: a shared key, never a user token."""
    if not settings.device_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Device ingestion not configured"
        )
    if x_device_key is None or not secrets.compare_digest(x_device_key, settings.device_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device key")


DeviceKeyDep = Annotated[None, Depends(require_device_key)]
```

`backend/src/app/presentation/http/errors.py` — add a handler:

```python
    @app.exception_handler(InvalidReading)
    async def _invalid_reading(_: Request, exc: InvalidReading) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)}
        )
```

`backend/src/app/presentation/http/sensors.py`:

```python
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.application.sensors.dtos import BucketOutput, DeviceOutput, ReadingInput, ReadingOutput
from app.application.sensors.queries import GetLatestReadings, GetReadings, ListDevices
from app.application.sensors.record import RecordReading
from app.presentation.dependencies import CurrentUserIdDep, DeviceKeyDep, HubDep, UowDep

router = APIRouter(prefix="/sensors", tags=["sensors"])

BUCKET_SECONDS: dict[str, int] = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
Bucket = Literal["1m", "5m", "15m", "1h"]


class GasPayload(BaseModel):
    mostGaz: bool = False  # noqa: N815 - key chosen by the firmware
    quantity: int | None = Field(default=None, ge=0)


class TemperaturePayload(BaseModel):
    humidity: float | None = None
    temp: float | None = None


class ReadingRequest(BaseModel):
    """Exactly what the ESP32 sends (see the « data ESP32 » note)."""

    device_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    recorded_at: datetime | None = None
    gaz: GasPayload | None = None
    temperature: TemperaturePayload | None = None

    def to_input(self) -> ReadingInput:
        return ReadingInput(
            device_id=self.device_id,
            recorded_at=self.recorded_at,
            temperature_c=self.temperature.temp if self.temperature else None,
            humidity_pct=self.temperature.humidity if self.temperature else None,
            gas_ppm=self.gaz.quantity if self.gaz else None,
            gas_alert=self.gaz.mostGaz if self.gaz else False,
        )


class ReadingResponse(BaseModel):
    id: UUID
    device_id: str
    recorded_at: datetime
    temperature_c: float | None
    humidity_pct: float | None
    gas_ppm: int | None
    gas_alert: bool

    @classmethod
    def from_output(cls, output: ReadingOutput) -> "ReadingResponse":
        return cls(
            id=output.id,
            device_id=output.device_id,
            recorded_at=output.recorded_at,
            temperature_c=output.temperature_c,
            humidity_pct=output.humidity_pct,
            gas_ppm=output.gas_ppm,
            gas_alert=output.gas_alert,
        )


class BucketResponse(BaseModel):
    bucket_start: datetime
    count: int
    temperature_avg: float | None
    temperature_min: float | None
    temperature_max: float | None
    humidity_avg: float | None
    humidity_min: float | None
    humidity_max: float | None
    gas_avg: float | None
    gas_min: int | None
    gas_max: int | None
    gas_alerts: int

    @classmethod
    def from_output(cls, output: BucketOutput) -> "BucketResponse":
        return cls(
            bucket_start=output.bucket_start, count=output.count,
            temperature_avg=output.temperature_avg, temperature_min=output.temperature_min,
            temperature_max=output.temperature_max, humidity_avg=output.humidity_avg,
            humidity_min=output.humidity_min, humidity_max=output.humidity_max,
            gas_avg=output.gas_avg, gas_min=output.gas_min, gas_max=output.gas_max,
            gas_alerts=output.gas_alerts,
        )


class DeviceResponse(BaseModel):
    device_id: str
    last_seen: datetime

    @classmethod
    def from_output(cls, output: DeviceOutput) -> "DeviceResponse":
        return cls(device_id=output.device_id, last_seen=output.last_seen)


def _utc(moment: datetime | None, default: datetime) -> datetime:
    if moment is None:
        return default
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


@router.post(
    "/readings",
    status_code=status.HTTP_201_CREATED,
    response_model=ReadingResponse,
    summary="Enregistre une mesure envoyée par un appareil",
    description="Authentification par l'en-tête `X-Device-Key` (réglage `DEVICE_API_KEY`). "
    "La mesure est stockée puis diffusée sur le WebSocket (`sensor.reading`).",
)
async def post_reading(
    body: ReadingRequest, _: DeviceKeyDep, uow: UowDep, hub: HubDep
) -> ReadingResponse:
    output = await RecordReading(uow=uow, broadcaster=hub).execute(body.to_input())
    return ReadingResponse.from_output(output)


@router.get(
    "/readings",
    response_model=list[ReadingResponse] | list[BucketResponse],
    summary="Historique des mesures d'un appareil",
    description="Sans `bucket` : mesures brutes (2000 max). Avec `bucket` (`1m`, `5m`, `15m`, "
    "`1h`) : moyennes, min, max et nombre d'alertes par intervalle. `from` vaut maintenant − 1 h "
    "par défaut, `to` maintenant.",
)
async def get_readings(
    _: CurrentUserIdDep,
    uow: UowDep,
    device_id: Annotated[str, Query(pattern=r"^[a-z0-9-]{1,64}$")],
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    bucket: Annotated[Bucket | None, Query()] = None,
) -> list[ReadingResponse] | list[BucketResponse]:
    now = datetime.now(UTC)
    since = _utc(from_, now - timedelta(hours=1))
    until = _utc(to, now)
    rows = await GetReadings(uow=uow).execute(
        device_id, since, until, BUCKET_SECONDS[bucket] if bucket else None
    )
    if bucket:
        return [BucketResponse.from_output(b) for b in rows]  # type: ignore[arg-type]
    return [ReadingResponse.from_output(r) for r in rows]  # type: ignore[arg-type]


@router.get("/latest", response_model=list[ReadingResponse], summary="Dernière mesure par appareil")
async def get_latest(_: CurrentUserIdDep, uow: UowDep) -> list[ReadingResponse]:
    return [ReadingResponse.from_output(r) for r in await GetLatestReadings(uow=uow).execute()]


@router.get("/devices", response_model=list[DeviceResponse], summary="Appareils connus")
async def get_devices(_: CurrentUserIdDep, uow: UowDep) -> list[DeviceResponse]:
    return [DeviceResponse.from_output(d) for d in await ListDevices(uow=uow).execute()]
```

`backend/src/app/presentation/main.py`: import `sensors` from `app.presentation.http` and `app.include_router(sensors.router)` after the camera router; extend the description with « , mesures capteurs ».

Note on `recorded_at` serialisation: pydantic serialises aware UTC datetimes as `…Z`; the tests accept `Z` (and the WebSocket event uses `isoformat()` → `+00:00`, which the front parses either way).

- [ ] **Step 4: Run the tests, ruff, commit**

Run: `uv run pytest -q` → all green (12 new). `uv run ruff check . && uv run ruff format .`.

```bash
cd /Users/namania/git/sentinel-x
git add backend
git commit -m "feat(backend): sensor routes with device key, history buckets and WebSocket push

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `simulate-sensors` developer command

**Files:**
- Create: `backend/src/app/presentation/simulate.py`
- Modify: `backend/pyproject.toml` (`[project.scripts]`), `backend/src/app/presentation/cli.py` (export only if needed — the entry point lives in `simulate.py`)
- Test: `backend/tests/unit/test_simulate_sensors.py`

**Interfaces:**
- Produces: `SensorWalk(rng).next_payload(device_id) -> dict` (ESP-format JSON), `run(base_url, device_key, device_id, interval, count, transport=None) -> int` (readings sent), console script `simulate-sensors`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_simulate_sensors.py`:

```python
import json
import random

import httpx

from app.presentation.simulate import SensorWalk, run


def test_walk_stays_within_plausible_bounds():
    walk = SensorWalk(random.Random(1))
    for _ in range(1000):
        p = walk.next_payload("esp-interieur")
        assert p["device_id"] == "esp-interieur"
        assert 15.0 <= p["temperature"]["temp"] <= 35.0
        assert 20.0 <= p["temperature"]["humidity"] <= 90.0
        assert 200 <= p["gaz"]["quantity"] <= 3000
        assert p["gaz"]["mostGaz"] == (p["gaz"]["quantity"] >= 1500)


def test_walk_produces_an_occasional_gas_alert():
    walk = SensorWalk(random.Random(7))
    alerts = sum(walk.next_payload("esp-interieur")["gaz"]["mostGaz"] for _ in range(2000))
    assert 0 < alerts < 400


def test_run_posts_readings_with_the_device_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"ok": True})

    sent = run(
        base_url="http://api.test",
        device_key="k" * 16,
        device_id="esp-interieur",
        interval=0,
        count=3,
        transport=httpx.MockTransport(handler),
    )
    assert sent == 3 and len(seen) == 3
    assert str(seen[0].url) == "http://api.test/sensors/readings"
    assert seen[0].headers["X-Device-Key"] == "k" * 16
    assert json.loads(seen[0].content)["device_id"] == "esp-interieur"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_simulate_sensors.py -q` → collection error (`app.presentation.simulate` missing).

- [ ] **Step 3: Implement**

`backend/src/app/presentation/simulate.py`:

```python
"""Send plausible fake readings to the API, to see the dashboard without hardware.

    uv run simulate-sensors [--base-url http://localhost:8000] [--device esp-interieur]
                            [--interval 2] [--count N]

The device key is read from DEVICE_API_KEY (the .env file is honoured through Settings).
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from typing import Any

import httpx

from app.infrastructure.config import Settings

GAS_ALERT_PPM = 1500


class SensorWalk:
    """Bounded random walk: small drifts, with an occasional gas spike."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self.temperature = 22.0
        self.humidity = 45.0
        self.gas = 400.0

    def _step(self, value: float, step: float, low: float, high: float) -> float:
        return min(high, max(low, value + self._rng.uniform(-step, step)))

    def next_payload(self, device_id: str) -> dict[str, Any]:
        self.temperature = self._step(self.temperature, 0.3, 15.0, 35.0)
        self.humidity = self._step(self.humidity, 1.0, 20.0, 90.0)
        if self._rng.random() < 0.02:  # a spike that takes a few readings to decay
            self.gas = min(3000.0, self.gas + self._rng.uniform(800, 1500))
        else:
            self.gas = self._step(self.gas * 0.9 + 40, 30, 200.0, 3000.0)
        quantity = int(round(self.gas))
        return {
            "device_id": device_id,
            "gaz": {"mostGaz": quantity >= GAS_ALERT_PPM, "quantity": quantity},
            "temperature": {"humidity": round(self.humidity, 1), "temp": round(self.temperature, 1)},
        }


def run(
    base_url: str,
    device_key: str,
    device_id: str,
    interval: float,
    count: int | None,
    transport: httpx.BaseTransport | None = None,
    log=print,
) -> int:
    walk = SensorWalk(random.Random())
    sent = 0
    with httpx.Client(base_url=base_url, transport=transport, timeout=5.0) as client:
        while count is None or sent < count:
            payload = walk.next_payload(device_id)
            response = client.post(
                "/sensors/readings", json=payload, headers={"X-Device-Key": device_key}
            )
            if response.status_code != 201:
                log(f"refusé ({response.status_code}) : {response.text}")
                break
            sent += 1
            log(
                f"{device_id}: {payload['temperature']['temp']} °C, "
                f"{payload['temperature']['humidity']} %, {payload['gaz']['quantity']} ppm"
                + (" ALERTE" if payload["gaz"]["mostGaz"] else "")
            )
            if count is None or sent < count:
                time.sleep(interval)
    return sent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Envoie des mesures factices à l'API.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--device", default="esp-interieur")
    parser.add_argument("--interval", type=float, default=2.0, help="secondes entre deux mesures")
    parser.add_argument("--count", type=int, default=None, help="nombre de mesures (infini sinon)")
    args = parser.parse_args(argv)
    key = Settings().device_api_key
    if not key:
        print("DEVICE_API_KEY manquant dans backend/.env", file=sys.stderr)
        return 2
    try:
        run(args.base_url, key, args.device, args.interval, args.count)
    except KeyboardInterrupt:
        pass
    return 0


def simulate_sensors_command() -> None:
    raise SystemExit(main())
```

`backend/pyproject.toml` — under `[project.scripts]` add `simulate-sensors = "app.presentation.simulate:simulate_sensors_command"`, then `uv sync` (re-installs the project so the script exists).

- [ ] **Step 4: Run the tests, ruff, commit**

Run: `uv run pytest tests/unit/test_simulate_sensors.py -q` → 3 passed; `uv run simulate-sensors --help` prints the usage; `uv run ruff check . && uv run ruff format .`.

```bash
cd /Users/namania/git/sentinel-x
git add backend/pyproject.toml backend/uv.lock backend/src/app/presentation/simulate.py backend/tests/unit/test_simulate_sensors.py
git commit -m "feat(backend): simulate-sensors command to feed fake readings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Front data layer — types, hooks, MSW fake endpoints, metric colors

**Files:**
- Create: `frontend/src/features/metrics/metrics-api.ts`, `frontend/src/features/metrics/use-readings.ts`, `frontend/src/features/metrics/use-sensor-stream.ts`, `frontend/src/test/sensors.ts`
- Modify: `frontend/src/test/server.ts` (handlers), `frontend/src/index.css` (metric colors)
- Test: `frontend/src/features/metrics/metrics-api.test.ts`, `frontend/src/features/metrics/use-readings.test.tsx`, `frontend/src/features/metrics/use-sensor-stream.test.tsx`

**Interfaces:**
- Produces:
  - `type Reading = { id; device_id; recorded_at; temperature_c: number|null; humidity_pct: number|null; gas_ppm: number|null; gas_alert: boolean }`, `type Bucket = {…}` (the BucketResponse fields), `type Device = { device_id; last_seen }`, `type Range = "15m" | "1h" | "6h" | "24h"`, `RANGES`, `RANGE_MS`, `RANGE_LABELS`, `bucketFor(range): "1m"|"5m"|"15m"|null`, `BUCKET_MS`, `readingsPath(deviceId, range, now)`, `DEVICES_PATH`, `LATEST_PATH`.
  - `type MetricPoint = { time: number; temperature: number|null; humidity: number|null; gas: number|null; gasAlert: boolean }`, `toPoints(rows, bucketed)`, `appendLive(points, reading, range, bucketMs)`.
  - `useReadings(deviceId, range): { status: "loading"|"ready"|"error"; points: MetricPoint[]; latest: Reading|null; previous: Reading|null; push(reading: Reading): void }`.
  - `useSensorStream(enabled: boolean, onReading: (r: Reading) => void): { connected: boolean }` with reconnection backoff `[1000, 2000, 5000, 10000, 30000]` ms.
  - Test fixtures: `makeReading(overrides)`, `readingsFixture(n, startMs)`, `bucketsFixture`, and MSW handlers for `/api/sensors/devices`, `/api/sensors/readings` (raw when no `bucket`, buckets otherwise), `/api/sensors/latest`; `sensorsLink = ws.link("ws://localhost:3000/ws")`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/test/sensors.ts` (fixtures, used by handlers and tests):

```ts
import type { Bucket, Reading } from "@/features/metrics/metrics-api";

export const DEVICE = "esp-interieur";

export function makeReading(overrides: Partial<Reading> = {}): Reading {
  return {
    id: crypto.randomUUID(),
    device_id: DEVICE,
    recorded_at: "2026-10-06T09:00:00Z",
    temperature_c: 22.5,
    humidity_pct: 48,
    gas_ppm: 410,
    gas_alert: false,
    ...overrides,
  };
}

/** n readings, one per minute, ending at `endMs`. */
export function readingsFixture(n: number, endMs: number): Reading[] {
  return Array.from({ length: n }, (_, i) =>
    makeReading({
      recorded_at: new Date(endMs - (n - 1 - i) * 60_000).toISOString(),
      temperature_c: 20 + i * 0.5,
      humidity_pct: 40 + i,
      gas_ppm: 400 + i * 10,
    }),
  );
}

export function bucketsFixture(n: number, endMs: number, bucketMs: number): Bucket[] {
  return Array.from({ length: n }, (_, i) => ({
    bucket_start: new Date(endMs - (n - 1 - i) * bucketMs).toISOString(),
    count: 5,
    temperature_avg: 21 + i,
    temperature_min: 20 + i,
    temperature_max: 22 + i,
    humidity_avg: 50,
    humidity_min: 45,
    humidity_max: 55,
    gas_avg: 500 + i * 100,
    gas_min: 450,
    gas_max: 550 + i * 100,
    gas_alerts: i === n - 1 ? 1 : 0,
  }));
}
```

Add to `frontend/src/test/server.ts` (imports `ws` from msw, the fixtures, `requireAccessToken` helper = the existing `isValidAccessToken(bearer(request))` check):

```ts
export const sensorsLink = ws.link("ws://localhost:3000/ws");
export const NOW_MS = Date.UTC(2026, 9, 6, 9, 0, 0);

export const sensorHandlers = [
  http.get("/api/sensors/devices", ({ request }) =>
    isValidAccessToken(bearer(request))
      ? HttpResponse.json([{ device_id: DEVICE, last_seen: new Date(NOW_MS).toISOString() }])
      : unauthenticated(),
  ),
  http.get("/api/sensors/latest", ({ request }) =>
    isValidAccessToken(bearer(request))
      ? HttpResponse.json([makeReading({ recorded_at: new Date(NOW_MS).toISOString() })])
      : unauthenticated(),
  ),
  http.get("/api/sensors/readings", ({ request }) => {
    if (!isValidAccessToken(bearer(request))) return unauthenticated();
    const url = new URL(request.url);
    const bucket = url.searchParams.get("bucket");
    if (bucket) {
      const ms = { "1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000 }[bucket] ?? 60_000;
      return HttpResponse.json(bucketsFixture(4, NOW_MS, ms));
    }
    return HttpResponse.json(readingsFixture(5, NOW_MS));
  }),
];
```

and spread `...sensorHandlers` into `handlers`.

Metric colors in `frontend/src/index.css` — inside `:root` add:

```css
  --metric-temperature: #d9541e;
  --metric-humidity: #2b6fd6;
  --metric-gas: #0f8f6a;
```

and inside `.dark`:

```css
  --metric-temperature: #e8622f;
  --metric-humidity: #4b8ae6;
  --metric-gas: #2aa87f;
```

`frontend/src/features/metrics/metrics-api.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { makeReading } from "@/test/sensors";
import { appendLive, bucketFor, readingsPath, toPoints } from "./metrics-api";

const NOW = Date.UTC(2026, 9, 6, 9, 0, 0);

describe("metrics api helpers", () => {
  it("picks the bucket from the range", () => {
    expect(bucketFor("15m")).toBeNull();
    expect(bucketFor("1h")).toBe("1m");
    expect(bucketFor("6h")).toBe("5m");
    expect(bucketFor("24h")).toBe("15m");
  });

  it("builds the history path with from and bucket", () => {
    expect(readingsPath("esp-interieur", "15m", NOW)).toBe(
      "/sensors/readings?device_id=esp-interieur&from=2026-10-06T08%3A45%3A00.000Z",
    );
    expect(readingsPath("esp-interieur", "6h", NOW)).toBe(
      "/sensors/readings?device_id=esp-interieur&from=2026-10-06T03%3A00%3A00.000Z&bucket=5m",
    );
  });

  it("maps raw readings and buckets to the same point shape", () => {
    const raw = toPoints([makeReading({ gas_ppm: 1600, gas_alert: true })], false);
    expect(raw[0]).toMatchObject({ temperature: 22.5, humidity: 48, gas: 1600, gasAlert: true });
    const bucketed = toPoints(
      [{ bucket_start: "2026-10-06T09:00:00Z", count: 2, temperature_avg: 21, temperature_min: 20,
         temperature_max: 22, humidity_avg: 50, humidity_min: 45, humidity_max: 55, gas_avg: null,
         gas_min: null, gas_max: null, gas_alerts: 0 }],
      true,
    );
    expect(bucketed[0]).toMatchObject({ temperature: 21, humidity: 50, gas: null, gasAlert: false });
  });

  it("appends a live reading as a new raw point and drops points outside the range", () => {
    const old = { time: NOW - 16 * 60_000, temperature: 1, humidity: 1, gas: 1, gasAlert: false };
    const points = appendLive([old], makeReading({ recorded_at: new Date(NOW).toISOString() }), "15m", null);
    expect(points).toHaveLength(1);
    expect(points[0].time).toBe(NOW);
  });

  it("folds a live reading into the current bucket when aggregated", () => {
    const current = { time: NOW - 30_000, temperature: 20, humidity: 40, gas: 400, gasAlert: false };
    const points = appendLive([current], makeReading({ recorded_at: new Date(NOW).toISOString(), gas_alert: true }), "1h", 60_000);
    expect(points).toHaveLength(1);
    expect(points[0]).toMatchObject({ time: NOW - 30_000, gasAlert: true });
    expect(points[0].temperature).toBeCloseTo(21.25);
  });
});
```

`frontend/src/features/metrics/use-readings.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderWithProviders } from "@/test/render";
import { makeReading, NOW_MS } from "@/test/sensors";
import { VALID_REFRESH, server } from "@/test/server";
import type { Range } from "./metrics-api";
import { useReadings } from "./use-readings";

function Probe({ range }: { range: Range }) {
  const { status, points, latest, previous, push } = useReadings("esp-interieur", range);
  return (
    <div>
      <p>status:{status}</p>
      <p>points:{points.length}</p>
      <p>latest:{latest?.temperature_c ?? "-"}</p>
      <p>previous:{previous?.temperature_c ?? "-"}</p>
      <button onClick={() => push(makeReading({ recorded_at: new Date(NOW_MS + 60_000).toISOString(), temperature_c: 30 }))}>
        push
      </button>
      <button onClick={() => push(makeReading({ device_id: "esp-ext", temperature_c: 99 }))}>push-other</button>
    </div>
  );
}

function renderProbe(range: Range) {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderWithProviders(<Probe range={range} />);
}

describe("useReadings", () => {
  it("loads raw readings for 15 minutes and derives latest and previous", async () => {
    const urls: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("/sensors/readings")) urls.push(request.url);
    });
    renderProbe("15m");
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("points:5")).toBeInTheDocument();
    expect(screen.getByText("latest:22")).toBeInTheDocument(); // last fixture: 20 + 4 * 0.5
    expect(screen.getByText("previous:21.5")).toBeInTheDocument();
    expect(urls[0]).not.toContain("bucket=");
  });

  it("requests buckets for an hour", async () => {
    const urls: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("/sensors/readings")) urls.push(request.url);
    });
    renderProbe("1h");
    await screen.findByText("status:ready");
    expect(urls[0]).toContain("bucket=1m");
    expect(screen.getByText("points:4")).toBeInTheDocument();
  });

  it("pushes a live reading of the same device and ignores other devices", async () => {
    const user = userEvent.setup();
    renderProbe("15m");
    await screen.findByText("status:ready");
    await user.click(screen.getByRole("button", { name: "push-other" }));
    expect(screen.getByText("points:5")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "push" }));
    expect(screen.getByText("points:6")).toBeInTheDocument();
    expect(screen.getByText("latest:30")).toBeInTheDocument();
    expect(screen.getByText("previous:22")).toBeInTheDocument();
  });

  it("reports an error when the API fails", async () => {
    server.use(http.get("/api/sensors/readings", () => HttpResponse.json({}, { status: 500 })));
    renderProbe("15m");
    expect(await screen.findByText("status:error")).toBeInTheDocument();
  });
});
```

`frontend/src/features/metrics/use-sensor-stream.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { makeReading } from "@/test/sensors";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import type { Reading } from "./metrics-api";
import { RECONNECT_DELAYS_MS, useSensorStream } from "./use-sensor-stream";

function Probe({ enabled }: { enabled: boolean }) {
  const [last, setLast] = useState<Reading | null>(null);
  const { connected } = useSensorStream(enabled, setLast);
  return (
    <div>
      <p>connected:{String(connected)}</p>
      <p>last:{last?.gas_ppm ?? "-"}</p>
    </div>
  );
}

function renderProbe(enabled = true) {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return render(
    <AuthProvider>
      <Probe enabled={enabled} />
    </AuthProvider>,
  );
}

describe("useSensorStream", () => {
  it("connects with the access token and delivers sensor.reading events", async () => {
    const tokens: string[] = [];
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        tokens.push(new URL(client.url).searchParams.get("token") ?? "");
        client.send(JSON.stringify({ type: "sensor.reading", data: makeReading({ gas_ppm: 777 }) }));
        client.send(JSON.stringify({ type: "pong" }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("connected:true")).toBeInTheDocument();
    expect(await screen.findByText("last:777")).toBeInTheDocument();
    expect(tokens[0]!.split(".")).toHaveLength(3);
  });

  it("does not connect when disabled", async () => {
    let connections = 0;
    server.use(sensorsLink.addEventListener("connection", () => void connections++));
    renderProbe(false);
    await new Promise((r) => setTimeout(r, 200));
    expect(connections).toBe(0);
    expect(screen.getByText("connected:false")).toBeInTheDocument();
  });

  it("reconnects after the server closes, waiting before each attempt", async () => {
    const times: number[] = [];
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        times.push(Date.now());
        if (times.length === 1) client.close();
      }),
    );
    renderProbe();
    await waitFor(() => expect(times).toHaveLength(2), { timeout: 4000 });
    expect(times[1]! - times[0]!).toBeGreaterThanOrEqual(RECONNECT_DELAYS_MS[0]! - 50);
  });

  it("closes the socket on unmount and stops reconnecting", async () => {
    let connections = 0;
    server.use(sensorsLink.addEventListener("connection", () => void connections++));
    const view = renderProbe();
    await screen.findByText("connected:true");
    view.unmount();
    await new Promise((r) => setTimeout(r, 1300));
    expect(connections).toBe(1);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test src/features/metrics`
Expected: FAIL — unresolved imports (`./metrics-api`, `./use-readings`, `./use-sensor-stream`, `@/test/sensors`).

- [ ] **Step 3: Implement**

`frontend/src/features/metrics/metrics-api.ts`:

```ts
export type Reading = {
  id: string;
  device_id: string;
  recorded_at: string;
  temperature_c: number | null;
  humidity_pct: number | null;
  gas_ppm: number | null;
  gas_alert: boolean;
};

export type Bucket = {
  bucket_start: string;
  count: number;
  temperature_avg: number | null;
  temperature_min: number | null;
  temperature_max: number | null;
  humidity_avg: number | null;
  humidity_min: number | null;
  humidity_max: number | null;
  gas_avg: number | null;
  gas_min: number | null;
  gas_max: number | null;
  gas_alerts: number;
};

export type Device = { device_id: string; last_seen: string };

export type Range = "15m" | "1h" | "6h" | "24h";
export const RANGES: readonly Range[] = ["15m", "1h", "6h", "24h"];
export const RANGE_LABELS: Record<Range, string> = { "15m": "15 min", "1h": "1 h", "6h": "6 h", "24h": "24 h" };
export const RANGE_MS: Record<Range, number> = {
  "15m": 15 * 60_000,
  "1h": 60 * 60_000,
  "6h": 6 * 60 * 60_000,
  "24h": 24 * 60 * 60_000,
};

export type BucketSize = "1m" | "5m" | "15m";
export const BUCKET_MS: Record<BucketSize, number> = { "1m": 60_000, "5m": 300_000, "15m": 900_000 };

/** Raw readings for a short range, averaged buckets beyond. */
export function bucketFor(range: Range): BucketSize | null {
  return { "15m": null, "1h": "1m", "6h": "5m", "24h": "15m" }[range];
}

export const DEVICES_PATH = "/sensors/devices";
export const LATEST_PATH = "/sensors/latest";

export function readingsPath(deviceId: string, range: Range, nowMs: number): string {
  const params = new URLSearchParams({
    device_id: deviceId,
    from: new Date(nowMs - RANGE_MS[range]).toISOString(),
  });
  const bucket = bucketFor(range);
  if (bucket) params.set("bucket", bucket);
  return `/sensors/readings?${params.toString()}`;
}

/** One chart point, whatever the source (raw reading or bucket average). */
export type MetricPoint = {
  time: number;
  temperature: number | null;
  humidity: number | null;
  gas: number | null;
  gasAlert: boolean;
};

export function readingToPoint(reading: Reading): MetricPoint {
  return {
    time: Date.parse(reading.recorded_at),
    temperature: reading.temperature_c,
    humidity: reading.humidity_pct,
    gas: reading.gas_ppm,
    gasAlert: reading.gas_alert,
  };
}

export function toPoints(rows: Reading[] | Bucket[], bucketed: boolean): MetricPoint[] {
  if (!bucketed) return (rows as Reading[]).map(readingToPoint);
  return (rows as Bucket[]).map((b) => ({
    time: Date.parse(b.bucket_start),
    temperature: b.temperature_avg,
    humidity: b.humidity_avg,
    gas: b.gas_avg,
    gasAlert: b.gas_alerts > 0,
  }));
}

function mean(current: number | null, incoming: number | null): number | null {
  if (current === null) return incoming;
  if (incoming === null) return current;
  return (current + incoming) / 2;
}

/**
 * Add a live reading to the series: as a new point when raw, folded into the current bucket
 * when aggregated (running mean, alert sticky). Points older than the range are dropped.
 */
export function appendLive(
  points: MetricPoint[],
  reading: Reading,
  range: Range,
  bucketMs: number | null,
): MetricPoint[] {
  const point = readingToPoint(reading);
  const cutoff = point.time - RANGE_MS[range];
  const kept = points.filter((p) => p.time >= cutoff);
  const last = kept.at(-1);
  if (bucketMs !== null && last && point.time - last.time < bucketMs) {
    const merged: MetricPoint = {
      time: last.time,
      temperature: mean(last.temperature, point.temperature),
      humidity: mean(last.humidity, point.humidity),
      gas: mean(last.gas, point.gas),
      gasAlert: last.gasAlert || point.gasAlert,
    };
    return [...kept.slice(0, -1), merged];
  }
  return [...kept, point];
}
```

`frontend/src/features/metrics/use-readings.ts`:

```ts
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import {
  appendLive,
  BUCKET_MS,
  bucketFor,
  readingsPath,
  toPoints,
  type Bucket,
  type MetricPoint,
  type Range,
  type Reading,
} from "./metrics-api";

type State = {
  status: "loading" | "ready" | "error";
  points: MetricPoint[];
  latest: Reading | null;
  previous: Reading | null;
};

const EMPTY: State = { status: "loading", points: [], latest: null, previous: null };

/** History of one device over a range, plus live readings pushed through `push`. */
export function useReadings(deviceId: string | null, range: Range) {
  const { authFetch } = useAuth();
  const [state, setState] = useState<State>(EMPTY);

  useEffect(() => {
    if (!deviceId) return;
    let cancelled = false;
    const bucket = bucketFor(range);
    authFetch<Reading[] | Bucket[]>(readingsPath(deviceId, range, Date.now()))
      .then((rows) => {
        if (cancelled) return;
        const points = toPoints(rows, bucket !== null);
        const raw = bucket === null ? (rows as Reading[]) : [];
        setState({
          status: "ready",
          points,
          latest: raw.at(-1) ?? null,
          previous: raw.at(-2) ?? null,
        });
      })
      .catch(() => {
        if (!cancelled) setState({ ...EMPTY, status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, deviceId, range]);

  const push = useCallback(
    (reading: Reading) => {
      if (reading.device_id !== deviceId) return;
      const bucket = bucketFor(range);
      setState((current) => ({
        ...current,
        points: appendLive(current.points, reading, range, bucket ? BUCKET_MS[bucket] : null),
        latest: reading,
        previous: current.latest,
      }));
    },
    [deviceId, range],
  );

  return { ...state, push };
}
```

When the range is bucketed, `latest`/`previous` start as `null` until a live reading arrives; Task 7 fills the tiles from `/sensors/latest` in that case.

`frontend/src/features/metrics/use-sensor-stream.ts`:

```ts
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import type { Reading } from "./metrics-api";

export const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000] as const;

export function streamUrl(token: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`;
}

/**
 * Listen to `sensor.reading` events on the app WebSocket. Reconnects with growing waits,
 * reopens when the access token changes, closes on unmount or when disabled.
 */
export function useSensorStream(enabled: boolean, onReading: (reading: Reading) => void) {
  const { accessToken } = useAuth();
  const [connected, setConnected] = useState(false);
  const onReadingRef = useRef(onReading);
  useEffect(() => {
    onReadingRef.current = onReading;
  }, [onReading]);

  useEffect(() => {
    if (!enabled || !accessToken) return;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let stopped = false;

    const connect = () => {
      socket = new WebSocket(streamUrl(accessToken));
      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(String(event.data)) as { type?: string; data?: Reading };
          if (message.type === "sensor.reading" && message.data) onReadingRef.current(message.data);
        } catch {
          // Not JSON: ignore.
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (stopped) return;
        const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)]!;
        attempt += 1;
        timer = setTimeout(connect, delay);
      };
      socket.onerror = () => socket?.close();
    };
    connect();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      socket?.close();
      setConnected(false);
    };
  }, [enabled, accessToken]);

  return { connected };
}
```

- [ ] **Step 4: Run the tests, then the toolchain, commit**

Run: `pnpm test src/features/metrics` → 13 passed.

```bash
cd /Users/namania/git/sentinel-x/frontend
pnpm format && pnpm lint && pnpm typecheck && pnpm test && pnpm build
cd .. && git add frontend && git commit -m "feat(frontend): metrics data layer: API types, history hook, live WebSocket stream

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Dashboard metrics section — filters, tiles, charts, table

**Files:**
- Create: `frontend/src/features/metrics/metrics-filters.tsx`, `frontend/src/features/metrics/metric-tiles.tsx`, `frontend/src/features/metrics/charts.tsx` (TemperatureChart, HumidityChart, GasChart, GasGauge), `frontend/src/features/metrics/readings-table.tsx`, `frontend/src/features/metrics/metrics-section.tsx`, `frontend/src/lib/format-number.ts`
- Modify: `frontend/src/pages/dashboard.tsx`
- Test: `frontend/src/features/metrics/metrics-section.test.tsx`, `frontend/src/lib/format-number.test.ts`

**Interfaces:**
- Consumes: Task 6 hooks and types; shadcn `ChartContainer`, `ChartTooltip`, `ChartTooltipContent`, `Select*`, `Switch`, `ToggleGroup`/`ToggleGroupItem`, `Table*`, `Badge`, `Card*`, `Skeleton`; Recharts `LineChart, Line, AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, RadialBarChart, RadialBar, PolarAngleAxis, Cell`.
- Produces: `<MetricsSection />` rendered by `DashboardPage` under the status cards; `formatNumber(value, digits)`, `formatTime(ms)`, `formatDelta(current, previous, digits)`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/format-number.test.ts`:

```ts
import { expect, it } from "vitest";
import { formatDelta, formatNumber, formatTime } from "./format-number";

it("formats numbers in French with fixed digits", () => {
  expect(formatNumber(22.456, 1)).toBe("22,5");
  expect(formatNumber(1500, 0)).toBe("1 500");
  expect(formatNumber(null, 1)).toBe("–");
});

it("formats a delta with its sign", () => {
  expect(formatDelta(22.5, 21.9, 1)).toBe("+0,6");
  expect(formatDelta(21.9, 22.5, 1)).toBe("−0,6");
  expect(formatDelta(22.5, null, 1)).toBeNull();
});

it("formats a time of day", () => {
  expect(formatTime(Date.UTC(2026, 9, 6, 9, 5, 0))).toBe("11:05"); // tests run in Europe/Paris
});
```

`frontend/src/features/metrics/metrics-section.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { routes } from "@/app/router";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { makeReading, NOW_MS, readingsFixture } from "@/test/sensors";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";

function renderDashboard() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes(routes, "/");
}

async function metrics() {
  return within(await screen.findByRole("region", { name: "Mesures" }));
}

describe("Dashboard metrics section", () => {
  it("shows the latest values in the tiles with their variation", async () => {
    renderDashboard();
    const section = await metrics();
    const temperature = within(await section.findByRole("group", { name: "Température" }));
    expect(await temperature.findByText("22,0")).toBeInTheDocument(); // last raw fixture
    expect(temperature.getByText("+0,5")).toBeInTheDocument();
    expect(within(section.getByRole("group", { name: "Humidité" })).getByText("44")).toBeInTheDocument();
    expect(within(section.getByRole("group", { name: "Gaz" })).getByText("440")).toBeInTheDocument();
    expect(section.queryByText("Alerte gaz")).not.toBeInTheDocument();
  });

  it("flags a gas alert on the gas tile", async () => {
    server.use(
      http.get("/api/sensors/readings", () =>
        HttpResponse.json([makeReading({ gas_ppm: 1800, gas_alert: true, recorded_at: new Date(NOW_MS).toISOString() })]),
      ),
    );
    renderDashboard();
    const section = await metrics();
    expect(await section.findByText("Alerte gaz")).toBeInTheDocument();
  });

  it("switches to the table view and lists the readings", async () => {
    const user = userEvent.setup();
    renderDashboard();
    const section = await metrics();
    await section.findByRole("group", { name: "Température" });
    await user.click(section.getByRole("radio", { name: "Tableau" }));
    const table = section.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(6); // header + 5 readings
    expect(within(table).getByText("22,0")).toBeInTheDocument();
  });

  it("reloads with buckets when the range changes", async () => {
    const urls: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("/sensors/readings")) urls.push(request.url);
    });
    const user = userEvent.setup();
    renderDashboard();
    const section = await metrics();
    await section.findByRole("group", { name: "Température" });
    await user.click(section.getByRole("radio", { name: "6 h" }));
    await waitFor(() => expect(urls.some((u) => u.includes("bucket=5m"))).toBe(true));
  });

  it("updates the tiles when a live reading arrives", async () => {
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        setTimeout(() => {
          client.send(JSON.stringify({ type: "sensor.reading", data: makeReading({ temperature_c: 31.4, recorded_at: new Date(NOW_MS + 60_000).toISOString() }) }));
          client.send(JSON.stringify({ type: "sensor.reading", data: makeReading({ device_id: "esp-ext", temperature_c: 5, recorded_at: new Date(NOW_MS + 61_000).toISOString() }) }));
        }, 50);
      }),
    );
    renderDashboard();
    const section = await metrics();
    const temperature = within(await section.findByRole("group", { name: "Température" }));
    expect(await temperature.findByText("31,4")).toBeInTheDocument();
    expect(temperature.queryByText("5,0")).not.toBeInTheDocument();
  });

  it("explains when there is no data", async () => {
    server.use(http.get("/api/sensors/readings", () => HttpResponse.json([])));
    renderDashboard();
    const section = await metrics();
    expect(
      await section.findByText("Aucune mesure pour cet appareil sur la plage choisie."),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `pnpm test src/features/metrics/metrics-section src/lib/format-number`
Expected: FAIL — no region « Mesures », missing module `./format-number`.

- [ ] **Step 3: Implement**

`frontend/src/lib/format-number.ts`:

```ts
const formatters = new Map<number, Intl.NumberFormat>();

function formatter(digits: number): Intl.NumberFormat {
  let f = formatters.get(digits);
  if (!f) {
    f = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    formatters.set(digits, f);
  }
  return f;
}

/** "22,5" — or an en dash when there is no value. */
export function formatNumber(value: number | null | undefined, digits: number): string {
  return value === null || value === undefined ? "–" : formatter(digits).format(value);
}

/** Signed variation, "+0,6" / "−0,6", or null when one side is missing. */
export function formatDelta(current: number | null, previous: number | null, digits: number): string | null {
  if (current === null || previous === null) return null;
  const delta = current - previous;
  const sign = delta < 0 ? "−" : "+";
  return `${sign}${formatter(digits).format(Math.abs(delta))}`;
}

const TIME = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

export function formatTime(ms: number): string {
  return TIME.format(new Date(ms));
}
```

`frontend/src/features/metrics/metrics-filters.tsx`:

```tsx
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { RANGE_LABELS, RANGES, type Device, type Range } from "./metrics-api";

export type View = "charts" | "table";

type Props = {
  devices: Device[];
  deviceId: string | null;
  onDeviceChange: (deviceId: string) => void;
  range: Range;
  onRangeChange: (range: Range) => void;
  live: boolean;
  onLiveChange: (live: boolean) => void;
  view: View;
  onViewChange: (view: View) => void;
};

export function MetricsFilters(props: Props) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="flex items-center gap-2">
        <Label htmlFor="metrics-device">Appareil</Label>
        <Select value={props.deviceId ?? undefined} onValueChange={props.onDeviceChange}>
          <SelectTrigger id="metrics-device" className="w-44">
            <SelectValue placeholder="Appareil" />
          </SelectTrigger>
          <SelectContent>
            {props.devices.map((d) => (
              <SelectItem key={d.device_id} value={d.device_id}>
                {d.device_id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <ToggleGroup
        type="single"
        value={props.range}
        onValueChange={(value) => value && props.onRangeChange(value as Range)}
        aria-label="Plage"
        variant="outline"
      >
        {RANGES.map((r) => (
          <ToggleGroupItem key={r} value={r}>
            {RANGE_LABELS[r]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <div className="flex items-center gap-2">
        <Switch id="metrics-live" checked={props.live} onCheckedChange={props.onLiveChange} />
        <Label htmlFor="metrics-live">Direct</Label>
      </div>
      <ToggleGroup
        type="single"
        value={props.view}
        onValueChange={(value) => value && props.onViewChange(value as View)}
        aria-label="Affichage"
        variant="outline"
        className="ml-auto"
      >
        <ToggleGroupItem value="charts">Graphiques</ToggleGroupItem>
        <ToggleGroupItem value="table">Tableau</ToggleGroupItem>
      </ToggleGroup>
    </div>
  );
}
```

Radix `ToggleGroup` items have `role="radio"` in single mode — the tests query them that way.

`frontend/src/features/metrics/metric-tiles.tsx`:

```tsx
import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDelta, formatNumber, formatTime } from "@/lib/format-number";
import type { Reading } from "./metrics-api";

type TileProps = {
  title: string;
  unit: string;
  value: number | null;
  previous: number | null;
  digits: number;
  color: string;
  at: number | null;
  alert?: boolean;
};

function Tile({ title, unit, value, previous, digits, color, at, alert }: TileProps) {
  const delta = formatDelta(value, previous, digits);
  return (
    <Card role="group" aria-label={title}>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <span className="inline-block size-2.5 rounded-full" style={{ background: color }} aria-hidden="true" />
          {title}
        </CardTitle>
        {alert && (
          <Badge variant="destructive" className="gap-1">
            <AlertTriangle className="size-3" aria-hidden="true" />
            Alerte gaz
          </Badge>
        )}
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-semibold tabular-nums">
          {formatNumber(value, digits)} <span className="text-muted-foreground text-base font-normal">{unit}</span>
        </p>
        <p className="text-muted-foreground mt-1 text-xs tabular-nums">
          {delta ? <span>{delta} {unit} </span> : null}
          {at ? <span>à {formatTime(at)}</span> : <span>En attente de mesure</span>}
        </p>
      </CardContent>
    </Card>
  );
}

export function MetricTiles({ latest, previous }: { latest: Reading | null; previous: Reading | null }) {
  const at = latest ? Date.parse(latest.recorded_at) : null;
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Tile title="Température" unit="°C" digits={1} color="var(--metric-temperature)" at={at}
        value={latest?.temperature_c ?? null} previous={previous?.temperature_c ?? null} />
      <Tile title="Humidité" unit="%" digits={0} color="var(--metric-humidity)" at={at}
        value={latest?.humidity_pct ?? null} previous={previous?.humidity_pct ?? null} />
      <Tile title="Gaz" unit="ppm" digits={0} color="var(--metric-gas)" at={at} alert={latest?.gas_alert}
        value={latest?.gas_ppm ?? null} previous={previous?.gas_ppm ?? null} />
    </div>
  );
}
```

`frontend/src/features/metrics/charts.tsx`:

```tsx
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { formatNumber, formatTime } from "@/lib/format-number";
import type { MetricPoint } from "./metrics-api";

const temperatureConfig = { temperature: { label: "Température (°C)", color: "var(--metric-temperature)" } } satisfies ChartConfig;
const humidityConfig = { humidity: { label: "Humidité (%)", color: "var(--metric-humidity)" } } satisfies ChartConfig;
const gasConfig = { gas: { label: "Gaz (ppm)", color: "var(--metric-gas)" } } satisfies ChartConfig;

const axisProps = {
  tickLine: false,
  axisLine: false,
  tickMargin: 8,
  minTickGap: 32,
} as const;

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

const tooltipLabel = (value: unknown) => formatTime(Number(value));

export function TemperatureChart({ points }: { points: MetricPoint[] }) {
  return (
    <ChartCard title="Température (°C)">
      <ChartContainer config={temperatureConfig} className="h-56 w-full">
        <LineChart data={points} margin={{ left: 0, right: 12 }}>
          <CartesianGrid vertical={false} strokeOpacity={0.4} />
          <XAxis dataKey="time" type="number" domain={["dataMin", "dataMax"]} tickFormatter={formatTime} {...axisProps} />
          <YAxis width={40} tickFormatter={(v) => formatNumber(Number(v), 0)} {...axisProps} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipLabel} />} />
          <Line dataKey="temperature" type="monotone" stroke="var(--color-temperature)" strokeWidth={2} dot={false} activeDot={{ r: 5 }} connectNulls />
        </LineChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function HumidityChart({ points }: { points: MetricPoint[] }) {
  return (
    <ChartCard title="Humidité (%)">
      <ChartContainer config={humidityConfig} className="h-56 w-full">
        <AreaChart data={points} margin={{ left: 0, right: 12 }}>
          <CartesianGrid vertical={false} strokeOpacity={0.4} />
          <XAxis dataKey="time" type="number" domain={["dataMin", "dataMax"]} tickFormatter={formatTime} {...axisProps} />
          <YAxis width={40} domain={[0, 100]} {...axisProps} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipLabel} />} />
          <Area dataKey="humidity" type="monotone" stroke="var(--color-humidity)" fill="var(--color-humidity)" fillOpacity={0.2} strokeWidth={2} connectNulls />
        </AreaChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function GasChart({ points }: { points: MetricPoint[] }) {
  return (
    <ChartCard title="Gaz (ppm, moyenne par intervalle)">
      <ChartContainer config={gasConfig} className="h-56 w-full">
        <BarChart data={points} margin={{ left: 0, right: 12 }} barCategoryGap={2}>
          <CartesianGrid vertical={false} strokeOpacity={0.4} />
          <XAxis dataKey="time" tickFormatter={formatTime} {...axisProps} />
          <YAxis width={48} tickFormatter={(v) => formatNumber(Number(v), 0)} {...axisProps} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipLabel} />} />
          <Bar dataKey="gas" fill="var(--color-gas)" radius={[4, 4, 0, 0]}>
            {points.map((p) => (
              <Cell key={p.time} fill={p.gasAlert ? "var(--destructive)" : "var(--color-gas)"} />
            ))}
          </Bar>
        </BarChart>
      </ChartContainer>
      <p className="text-muted-foreground mt-2 text-xs">
        Les intervalles contenant une alerte sont en rouge.
      </p>
    </ChartCard>
  );
}

export function GasGauge({ value, max }: { value: number | null; max: number }) {
  const ratio = value === null ? 0 : Math.min(1, value / Math.max(max, 1));
  const data = [{ name: "gas", value: ratio * 100 }];
  return (
    <ChartCard title="Gaz : dernière valeur vs maximum de la plage">
      <ChartContainer config={gasConfig} className="mx-auto aspect-square h-56">
        <RadialBarChart data={data} innerRadius="70%" outerRadius="100%" startAngle={210} endAngle={-30}>
          <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
          <RadialBar dataKey="value" background cornerRadius={4} fill="var(--color-gas)" />
        </RadialBarChart>
      </ChartContainer>
      <p className="text-center text-2xl font-semibold tabular-nums">
        {formatNumber(value, 0)} <span className="text-muted-foreground text-sm font-normal">/ {formatNumber(max, 0)} ppm</span>
      </p>
    </ChartCard>
  );
}
```

`frontend/src/features/metrics/readings-table.tsx`:

```tsx
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatNumber, formatTime } from "@/lib/format-number";
import type { MetricPoint } from "./metrics-api";

export function ReadingsTable({ points, bucketed }: { points: MetricPoint[]; bucketed: boolean }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{bucketed ? "Intervalle" : "Heure"}</TableHead>
          <TableHead className="text-right">Température (°C)</TableHead>
          <TableHead className="text-right">Humidité (%)</TableHead>
          <TableHead className="text-right">Gaz (ppm)</TableHead>
          <TableHead>Alerte</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {[...points].reverse().map((p) => (
          <TableRow key={p.time}>
            <TableCell>{formatTime(p.time)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatNumber(p.temperature, 1)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatNumber(p.humidity, 0)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatNumber(p.gas, 0)}</TableCell>
            <TableCell>{p.gasAlert ? "Alerte gaz" : "–"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

`frontend/src/features/metrics/metrics-section.tsx`:

```tsx
import { useCallback, useEffect, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/features/auth/use-auth";
import { GasChart, GasGauge, HumidityChart, TemperatureChart } from "./charts";
import { MetricTiles } from "./metric-tiles";
import { bucketFor, DEVICES_PATH, LATEST_PATH, type Device, type Range, type Reading } from "./metrics-api";
import { MetricsFilters, type View } from "./metrics-filters";
import { ReadingsTable } from "./readings-table";
import { useReadings } from "./use-readings";
import { useSensorStream } from "./use-sensor-stream";

export function MetricsSection() {
  const { authFetch } = useAuth();
  const [devices, setDevices] = useState<Device[]>([]);
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [range, setRange] = useState<Range>("15m");
  const [live, setLive] = useState(true);
  const [view, setView] = useState<View>("charts");
  const [latestFromApi, setLatestFromApi] = useState<Reading | null>(null);

  useEffect(() => {
    let cancelled = false;
    authFetch<Device[]>(DEVICES_PATH)
      .then((list) => {
        if (cancelled) return;
        setDevices(list);
        setDeviceId((current) => current ?? list[0]?.device_id ?? null);
      })
      .catch(() => {
        if (!cancelled) setDevices([]);
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  // Tiles need the very last reading even when the range is bucketed.
  useEffect(() => {
    if (!deviceId) return;
    let cancelled = false;
    authFetch<Reading[]>(LATEST_PATH)
      .then((rows) => {
        if (!cancelled) setLatestFromApi(rows.find((r) => r.device_id === deviceId) ?? null);
      })
      .catch(() => {
        if (!cancelled) setLatestFromApi(null);
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, deviceId]);

  const readings = useReadings(deviceId, range);
  const onReading = useCallback((reading: Reading) => readings.push(reading), [readings.push]);
  useSensorStream(live && deviceId !== null, onReading);

  const bucketed = bucketFor(range) !== null;
  const latest = readings.latest ?? latestFromApi;
  const previous = readings.previous;
  const gasMax = Math.max(0, ...readings.points.map((p) => p.gas ?? 0));

  return (
    <section aria-labelledby="metrics-title" className="space-y-4">
      <h2 id="metrics-title" className="text-xl font-semibold">
        Mesures
      </h2>
      <MetricsFilters
        devices={devices}
        deviceId={deviceId}
        onDeviceChange={setDeviceId}
        range={range}
        onRangeChange={setRange}
        live={live}
        onLiveChange={setLive}
        view={view}
        onViewChange={setView}
      />
      <MetricTiles latest={latest} previous={previous} />
      {readings.status === "loading" && <Skeleton className="h-56 w-full" />}
      {readings.status === "error" && <p className="text-destructive">Impossible de charger les mesures.</p>}
      {readings.status === "ready" && readings.points.length === 0 && (
        <p className="text-muted-foreground">Aucune mesure pour cet appareil sur la plage choisie.</p>
      )}
      {readings.status === "ready" && readings.points.length > 0 && view === "charts" && (
        <div className="grid gap-4 xl:grid-cols-2">
          <TemperatureChart points={readings.points} />
          <HumidityChart points={readings.points} />
          <GasChart points={readings.points} />
          <GasGauge value={latest?.gas_ppm ?? null} max={gasMax} />
        </div>
      )}
      {readings.status === "ready" && readings.points.length > 0 && view === "table" && (
        <ReadingsTable points={readings.points} bucketed={bucketed} />
      )}
    </section>
  );
}
```

The `<section aria-labelledby>` gives the test its `region` named « Mesures ». `onReading` depends on `readings.push`, which `useReadings` memoises on `(deviceId, range)` — write the dependency as `[readings.push]` exactly; the react-hooks lint rule accepts a property of a hook result.

`frontend/src/pages/dashboard.tsx` — render `<MetricsSection />` after the cards grid:

```tsx
import { AccountCard, ApiCard, CameraCard } from "@/features/dashboard/status-cards";
import { MetricsSection } from "@/features/metrics/metrics-section";
import { useDocumentTitle } from "@/lib/use-document-title";

export function DashboardPage() {
  useDocumentTitle("Dashboard · sentinel-x");
  return (
    <section className="flex flex-1 flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <CameraCard />
        <ApiCard />
        <AccountCard />
      </div>
      <MetricsSection />
    </section>
  );
}
```

Recharts under jsdom: `ChartContainer` renders a `ResponsiveContainer` with `initialDimension`, so the charts mount without errors but draw nothing measurable; the tests assert tiles, table and copy. If Recharts logs a width/height warning in the test output, pass `initialDimension={{ width: 600, height: 224 }}` on each `ChartContainer` (a prop the shadcn wrapper exposes) and the warning disappears — test output must stay clean.

- [ ] **Step 4: Run the tests, toolchain, commit**

Run: `pnpm test src/features/metrics src/lib/format-number src/pages` → all green (3 + 6 new, dashboard tests still passing).

```bash
cd /Users/namania/git/sentinel-x/frontend
pnpm format && pnpm lint && pnpm typecheck && pnpm test && pnpm build
cd .. && git add frontend && git commit -m "feat(frontend): metrics section in the dashboard: tiles, charts, table, live updates

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: README, spec notes, end-to-end check

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-06-sensor-metrics-design.md` (status line)

- [ ] **Step 1: README**

Add a « Capteurs » section before « Front »:

```markdown
## Capteurs

Les ESP32 envoient leurs mesures en HTTP (MQTT viendra plus tard) :

```sh
curl -X POST http://<hôte>:8080/api/sensors/readings \
  -H "X-Device-Key: $DEVICE_API_KEY" -H "Content-Type: application/json" \
  -d '{"device_id":"esp-interieur","gaz":{"mostGaz":false,"quantity":412},"temperature":{"humidity":48.5,"temp":22.9}}'
```

`DEVICE_API_KEY` (16 caractères minimum) se règle dans `backend/.env`. Chaque mesure est stockée
puis diffusée sur le WebSocket (`{"type":"sensor.reading","data":{…}}`). Historique :
`GET /api/sensors/readings?device_id=…&from=…&to=…&bucket=1m|5m|15m|1h`, dernière mesure par
appareil : `GET /api/sensors/latest`, appareils : `GET /api/sensors/devices`.

Sans matériel : `cd backend && uv run simulate-sensors` envoie des mesures factices toutes les 2 s
(`--base-url`, `--device`, `--interval`, `--count`). Les graphiques sont dans le Dashboard.
```

Add to the URL list: `- Mesures : section « Mesures » du Dashboard (temps réel via le WebSocket)`.

- [ ] **Step 2: Spec status**

Change the spec's « Statut » line to « implémenté le 2026-10-06 ».

- [ ] **Step 3: End-to-end check against the dev stack (no commit)**

With `make dev` running and `DEVICE_API_KEY` set in `backend/.env` (then `docker compose -f compose.yml -f compose.dev.yml up -d api` to reload the env): run `cd backend && uv run simulate-sensors --count 20 --interval 0.5`, open `http://localhost:8080/`, confirm the tiles and charts fill and move while the simulator runs. If the API container has no `DEVICE_API_KEY`, the simulator prints `refusé (503)`.

- [ ] **Step 4: Commit**

```bash
cd /Users/namania/git/sentinel-x
git add README.md docs/superpowers/specs/2026-10-06-sensor-metrics-design.md
git commit -m "docs: sensor ingestion, simulator and dashboard metrics

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Done criteria

- Backend: `uv run ruff check . && uv run pytest -q` green (about 30 new tests); `uv run simulate-sensors --help` works.
- Front: `pnpm format && pnpm lint && pnpm typecheck && pnpm test && pnpm build` green (about 25 new tests), no Recharts warnings in the test output.
- Posting a reading with the device key makes a connected browser's dashboard tiles move without reload.
