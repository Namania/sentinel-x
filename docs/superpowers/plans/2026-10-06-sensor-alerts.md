# Alertes capteurs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open a persisted alert when a sensor reading leaves its bounds, resolve it automatically when the reading comes back (with hysteresis), push both on the WebSocket, and show the list on the Dashboard, on a `/alertes` page, in the nav badge and on the sensor tiles.

**Architecture:** Pure domain functions (`violations`, `back_in_range`) decide; `RecordReading` applies them in the same transaction as the reading through a new `AlertRepository` on the unit of work, then broadcasts `alert.opened` / `alert.resolved` after `sensor.reading`. Thresholds come from `Settings`. The front gets a `features/alerts/` feature built on `useEventStream`, mounted once in the Dashboard page and shared by the card and the tiles.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, pydantic-settings, pytest; React 19, TypeScript, shadcn (`badge`, `card`, `table`, `select`, `toggle-group`), React Router 8, Vitest + MSW 3.

**Spec:** `docs/superpowers/specs/2026-10-06-sensor-alerts-design.md`

## Global Constraints

- Backend: ruff `line-length = 100`, rules `E F I UP B`; `uv run` for every command; integration tests need the compose Postgres (`docker compose up -d db`).
- Thresholds defaults verbatim: temperature 10.0–30.0 °C, humidity 20.0–70.0 %, `alert_gas_max_mv = None`. Margins are domain constants: `TEMPERATURE_MARGIN_C = 0.5`, `HUMIDITY_MARGIN_PCT = 2.0`, `GAS_MARGIN_RATIO = 0.05`.
- One open alert per (device_id, metric), enforced by a partial unique index `uq_alerts_open_per_metric … WHERE resolved_at IS NULL`.
- `opened_at` / `resolved_at` take the reading's plausible `recorded_at`, never processing time.
- Events: `sensor.reading` first, then alert events; dates serialised as `…Z`.
- Frontend: French UI copy; numbers through `src/lib/format-number.ts`; colour never the only signal (« Ouverte » / « Résolue » words next to the dot); no controls inside a `<Link>`.
- Frontend toolchain before each commit: `pnpm format && pnpm lint && pnpm typecheck && pnpm test && pnpm build` from `frontend/`.
- Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; branch `feat/sensor-alerts` cut from `main`; linear history; absolute paths in shell commands.

## Review Focus

1. Two readings for the same device arrive concurrently (MQTT + HTTP): the second `open_for` sees no open alert and both try to insert → the partial unique index must raise, and the use case must not leave a half-stored reading. Test the index in Task 3; the use case commits reading + alert together so a failure rolls both back (Task 4 integration test posts twice sequentially; the concurrent case is covered by the DB constraint).
2. A reading with `temperature_c = None` while a temperature alert is open: the alert must stay open (unknown ≠ back in range). Test in Task 1 and Task 4.
3. Gas alert raised by the ESP flag while `alert_gas_max_mv` is unset: `threshold = 0`, `describeAlert()` must say « Gaz : alerte ESP », not « Gaz 0 mV > 0 mV ». Tests in Task 1 (domain) and Task 7 (front).
4. A reading that oscillates just under the bound (29.8 °C after a 30.4 °C peak): the alert must stay open until ≤ 29.5 °C. Test in Task 1 and Task 4.
5. The front receives `alert.resolved` for an alert it never saw opened (list limit or late join): `upsert` must add it, not drop it. Test in Task 7.

---

## File structure

Backend (new): `domain/alert.py`; `application/alerts/__init__.py`, `application/alerts/dtos.py`; `alembic/versions/0004_create_alerts.py`; `presentation/http/alerts.py`.
Backend (modified): `domain/repositories.py`, `application/ports/unit_of_work.py`, `infrastructure/config.py`, `infrastructure/db/models.py`, `infrastructure/db/repositories.py`, `infrastructure/db/unit_of_work.py`, `application/sensors/record.py`, `infrastructure/mqtt/subscriber.py`, `presentation/http/sensors.py`, `presentation/dependencies.py`, `presentation/main.py`, `presentation/simulate.py`, `tests/unit/fakes.py`.
Frontend (new): `features/alerts/alerts-api.ts`, `use-alerts.ts`, `use-alert-count.ts`, `alert-row.tsx`, `alerts-card.tsx`, `alerts-page-content.tsx`; `pages/alerts.tsx`; `test/alerts.ts`.
Frontend (modified): `test/server.ts`, `features/metrics/metric-tiles.tsx`, `features/metrics/metrics-section.tsx` (+test), `pages/dashboard.tsx` (+test), `app/router.tsx`, `app/app-shell.tsx`, `components/app-sidebar.tsx` (+test).

---

## Task 0: Branch

- [ ] **Step 1**

```bash
cd /Users/namania/git/sentinel-x && git checkout -q main && git checkout -b feat/sensor-alerts && git log --oneline -1
```

Expected: on `feat/sensor-alerts` at the commit of the spec (`857a5e8` or later).

---

### Task 1: Domain — `Thresholds`, `Alert`, `violations`, `back_in_range`

**Files:**
- Create: `backend/src/app/domain/alert.py`
- Test: `backend/tests/unit/test_alert_domain.py`

**Interfaces:**
- Produces: `Metric`, `Direction`, `METRICS`, margins, `Thresholds(temperature, humidity, gas_max)`, `DEFAULT_THRESHOLDS`, `Violation(metric, direction, threshold, value)`, `Alert` (fields per spec; `Alert.open(*, device_id, metric, direction, threshold, at, value)`, `is_open`, `worsen(value)`, `resolve(at, value)`), `violations(reading, t) -> dict[Metric, Violation | None]`, `back_in_range(alert, reading, t) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_alert_domain.py
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.alert import (
    DEFAULT_THRESHOLDS,
    Alert,
    Thresholds,
    Violation,
    back_in_range,
    violations,
)
from app.domain.sensor_reading import SensorReading

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def reading(temp=22.0, hum=50.0, gas=400, flag=False, minutes=0) -> SensorReading:
    return SensorReading.create(
        device_id="esp-interieur",
        recorded_at=T0 + timedelta(minutes=minutes),
        temperature_c=temp,
        humidity_pct=hum,
        gas_level=gas,
        gas_alert=flag,
    )


def test_defaults_match_the_spec():
    assert DEFAULT_THRESHOLDS == Thresholds(temperature=(10.0, 30.0), humidity=(20.0, 70.0), gas_max=None)


def test_thresholds_reject_inverted_bounds():
    with pytest.raises(ValueError):
        Thresholds(temperature=(30.0, 10.0), humidity=(20.0, 70.0), gas_max=None)
    with pytest.raises(ValueError):
        Thresholds(temperature=(10.0, 30.0), humidity=(70.0, 70.0), gas_max=None)


def test_in_range_reading_has_no_violation():
    assert violations(reading(), DEFAULT_THRESHOLDS) == {
        "temperature": None,
        "humidity": None,
        "gas": None,
    }


def test_temperature_and_humidity_violations_carry_direction_and_bound():
    v = violations(reading(temp=30.4, hum=12.0), DEFAULT_THRESHOLDS)
    assert v["temperature"] == Violation("temperature", "high", 30.0, 30.4)
    assert v["humidity"] == Violation("humidity", "low", 20.0, 12.0)


def test_missing_values_are_not_violations():
    v = violations(reading(temp=None, hum=None, gas=None), DEFAULT_THRESHOLDS)
    assert v == {"temperature": None, "humidity": None, "gas": None}


def test_gas_alert_by_device_flag_has_a_zero_threshold_when_no_bound_is_set():
    v = violations(reading(gas=1800, flag=True), DEFAULT_THRESHOLDS)
    assert v["gas"] == Violation("gas", "high", 0.0, 1800.0)


def test_gas_alert_by_bound():
    t = Thresholds(temperature=(10.0, 30.0), humidity=(20.0, 70.0), gas_max=1500)
    assert violations(reading(gas=1600), t)["gas"] == Violation("gas", "high", 1500.0, 1600.0)
    assert violations(reading(gas=1500), t)["gas"] is None
    assert violations(reading(gas=None, flag=True), t)["gas"] == Violation("gas", "high", 1500.0, 0.0)


def open_alert(metric="temperature", direction="high", threshold=30.0, value=30.4) -> Alert:
    return Alert.open(
        device_id="esp-interieur",
        metric=metric,
        direction=direction,
        threshold=threshold,
        at=T0,
        value=value,
    )


def test_open_alert_fields():
    a = open_alert()
    assert a.is_open
    assert (a.opened_at, a.opened_value, a.peak_value) == (T0, 30.4, 30.4)
    assert (a.resolved_at, a.resolved_value) == (None, None)


def test_worsen_keeps_the_worst_value_per_direction():
    high = open_alert()
    assert high.worsen(31.2).peak_value == 31.2
    assert high.worsen(30.1) is high
    low = open_alert(direction="low", threshold=10.0, value=9.0)
    assert low.worsen(7.5).peak_value == 7.5
    assert low.worsen(9.5) is low


def test_resolve_closes_the_alert():
    a = open_alert()
    done = a.resolve(at=T0 + timedelta(minutes=3), value=29.1)
    assert not done.is_open
    assert done.id == a.id
    assert (done.resolved_at, done.resolved_value) == (T0 + timedelta(minutes=3), 29.1)


def test_hysteresis_keeps_the_alert_open_just_under_the_bound():
    a = open_alert()
    assert back_in_range(a, reading(temp=29.8), DEFAULT_THRESHOLDS) is False
    assert back_in_range(a, reading(temp=29.5), DEFAULT_THRESHOLDS) is True
    low = open_alert(direction="low", threshold=10.0, value=9.0)
    assert back_in_range(low, reading(temp=10.2), DEFAULT_THRESHOLDS) is False
    assert back_in_range(low, reading(temp=10.5), DEFAULT_THRESHOLDS) is True


def test_humidity_hysteresis_is_two_points():
    a = open_alert(metric="humidity", threshold=70.0, value=72.0)
    assert back_in_range(a, reading(hum=69.0), DEFAULT_THRESHOLDS) is False
    assert back_in_range(a, reading(hum=68.0), DEFAULT_THRESHOLDS) is True


def test_missing_value_never_resolves():
    a = open_alert()
    assert back_in_range(a, reading(temp=None), DEFAULT_THRESHOLDS) is False


def test_gas_resolves_when_the_flag_drops_and_the_level_is_under_the_margin():
    flag_only = open_alert(metric="gas", threshold=0.0, value=1800.0)
    assert back_in_range(flag_only, reading(gas=1800, flag=True), DEFAULT_THRESHOLDS) is False
    assert back_in_range(flag_only, reading(gas=1800, flag=False), DEFAULT_THRESHOLDS) is True
    t = Thresholds(temperature=(10.0, 30.0), humidity=(20.0, 70.0), gas_max=1500)
    bounded = open_alert(metric="gas", threshold=1500.0, value=1600.0)
    assert back_in_range(bounded, reading(gas=1450, flag=False), t) is False  # > 0.95 × 1500
    assert back_in_range(bounded, reading(gas=1425, flag=False), t) is True
    assert back_in_range(bounded, reading(gas=None, flag=False), t) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_alert_domain.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.alert'`.

- [ ] **Step 3: Implement**

```python
# backend/src/app/domain/alert.py
"""Alerts: a reading left its bounds; the alert lives until a reading comes back inside them."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from app.domain.sensor_reading import SensorReading

Metric = Literal["temperature", "humidity", "gas"]
Direction = Literal["low", "high"]
METRICS: tuple[Metric, ...] = ("temperature", "humidity", "gas")

# Hysteresis: an open alert closes only once the value is this far back inside the bound.
TEMPERATURE_MARGIN_C = 0.5
HUMIDITY_MARGIN_PCT = 2.0
GAS_MARGIN_RATIO = 0.05


@dataclass(frozen=True, slots=True)
class Thresholds:
    temperature: tuple[float, float]  # (min, max) °C
    humidity: tuple[float, float]  # (min, max) %
    gas_max: int | None  # mV; None → only the device's own alert flag counts

    def __post_init__(self) -> None:
        for name, (low, high) in (("temperature", self.temperature), ("humidity", self.humidity)):
            if not low < high:
                raise ValueError(f"{name} bounds must satisfy min < max (got {low:g} ≥ {high:g})")


DEFAULT_THRESHOLDS = Thresholds(temperature=(10.0, 30.0), humidity=(20.0, 70.0), gas_max=None)


@dataclass(frozen=True, slots=True)
class Violation:
    metric: Metric
    direction: Direction
    threshold: float
    value: float


@dataclass(frozen=True, slots=True)
class Alert:
    id: UUID
    device_id: str
    metric: Metric
    direction: Direction
    threshold: float
    opened_at: datetime
    opened_value: float
    peak_value: float
    resolved_at: datetime | None
    resolved_value: float | None

    @classmethod
    def open(
        cls,
        *,
        device_id: str,
        metric: Metric,
        direction: Direction,
        threshold: float,
        at: datetime,
        value: float,
    ) -> Alert:
        return cls(
            id=uuid4(),
            device_id=device_id,
            metric=metric,
            direction=direction,
            threshold=threshold,
            opened_at=at,
            opened_value=value,
            peak_value=value,
            resolved_at=None,
            resolved_value=None,
        )

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None

    def worsen(self, value: float) -> Alert:
        """The same alert with `value` as peak when it is worse than the current one."""
        worse = value > self.peak_value if self.direction == "high" else value < self.peak_value
        return replace(self, peak_value=value) if worse else self

    def resolve(self, at: datetime, value: float) -> Alert:
        return replace(self, resolved_at=at, resolved_value=value)


def _bounded(metric: Metric, value: float | None, bounds: tuple[float, float]) -> Violation | None:
    if value is None:
        return None
    low, high = bounds
    if value < low:
        return Violation(metric, "low", low, value)
    if value > high:
        return Violation(metric, "high", high, value)
    return None


def _gas(reading: SensorReading, t: Thresholds) -> Violation | None:
    level = float(reading.gas_level) if reading.gas_level is not None else 0.0
    if reading.gas_alert:
        return Violation("gas", "high", float(t.gas_max or 0), level)
    if t.gas_max is not None and reading.gas_level is not None and reading.gas_level > t.gas_max:
        return Violation("gas", "high", float(t.gas_max), level)
    return None


def violations(reading: SensorReading, t: Thresholds) -> dict[Metric, Violation | None]:
    """Which bounds this reading breaks; a missing value breaks nothing (we do not know)."""
    return {
        "temperature": _bounded("temperature", reading.temperature_c, t.temperature),
        "humidity": _bounded("humidity", reading.humidity_pct, t.humidity),
        "gas": _gas(reading, t),
    }


def _inside_with_margin(
    alert: Alert, value: float | None, bounds: tuple[float, float], margin: float
) -> bool:
    if value is None:
        return False
    low, high = bounds
    return value <= high - margin if alert.direction == "high" else value >= low + margin


def back_in_range(alert: Alert, reading: SensorReading, t: Thresholds) -> bool:
    """True when `reading` is far enough inside the bound to close `alert` (hysteresis)."""
    if alert.metric == "temperature":
        return _inside_with_margin(alert, reading.temperature_c, t.temperature, TEMPERATURE_MARGIN_C)
    if alert.metric == "humidity":
        return _inside_with_margin(alert, reading.humidity_pct, t.humidity, HUMIDITY_MARGIN_PCT)
    if reading.gas_alert:
        return False
    if t.gas_max is None:
        return True
    if reading.gas_level is None:
        return False
    return reading.gas_level <= t.gas_max * (1 - GAS_MARGIN_RATIO)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_alert_domain.py -q && uv run ruff check . && uv run ruff format --check .`
Expected: `15 passed`, ruff clean (run `uv run ruff format .` if a line exceeds 100 columns).

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend/src/app/domain/alert.py backend/tests/unit/test_alert_domain.py && git commit -q -m "$(cat <<'EOF'
feat(alerts): domain thresholds, alert entity, violation and hysteresis rules

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Settings thresholds

**Files:**
- Modify: `backend/src/app/infrastructure/config.py`
- Test: `backend/tests/unit/test_settings.py` (append)

**Interfaces:**
- Consumes: `Thresholds` (Task 1).
- Produces: settings `alert_temperature_min_c`, `alert_temperature_max_c`, `alert_humidity_min_pct`, `alert_humidity_max_pct`, `alert_gas_max_mv`; method `Settings.thresholds() -> Thresholds`; inverted bounds → `ValidationError`.

- [ ] **Step 1: Write the failing tests**

```python
def test_alert_thresholds_defaults_and_accessor():
    from app.domain.alert import Thresholds

    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.thresholds() == Thresholds(
        temperature=(10.0, 30.0), humidity=(20.0, 70.0), gas_max=None
    )


def test_alert_thresholds_from_env_and_inverted_bounds_rejected(monkeypatch):
    monkeypatch.setenv("ALERT_TEMPERATURE_MAX_C", "28")
    monkeypatch.setenv("ALERT_GAS_MAX_MV", "1500")
    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.thresholds().temperature == (10.0, 28.0)
    assert settings.thresholds().gas_max == 1500
    monkeypatch.setenv("ALERT_HUMIDITY_MIN_PCT", "80")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="x" * 32)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_settings.py -q`
Expected: 2 FAIL (`AttributeError: 'Settings' object has no attribute 'thresholds'`).

- [ ] **Step 3: Implement**

In `config.py`: import `from pydantic import field_validator, model_validator` (keep the existing `field_validator` import) and `from app.domain.alert import Thresholds`. Add after the server-health block:

```python
    # Sensor alert bounds, the same for every device; a reading outside opens an alert.
    alert_temperature_min_c: float = 10.0
    alert_temperature_max_c: float = 30.0
    alert_humidity_min_pct: float = 20.0
    alert_humidity_max_pct: float = 70.0
    alert_gas_max_mv: int | None = None  # None → only the device's own gas alert flag counts

    def thresholds(self) -> Thresholds:
        return Thresholds(
            temperature=(self.alert_temperature_min_c, self.alert_temperature_max_c),
            humidity=(self.alert_humidity_min_pct, self.alert_humidity_max_pct),
            gas_max=self.alert_gas_max_mv,
        )

    @model_validator(mode="after")
    def _alert_bounds_must_be_ordered(self) -> "Settings":
        self.thresholds()  # raises ValueError on min >= max → ValidationError
        return self
```

If `alert_gas_max_mv=""` (empty line in `.env`) must mean None, add a `field_validator("alert_gas_max_mv", mode="before")` returning `None` for `""`, like `device_api_key`.

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_settings.py -q && uv run ruff check .`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend/src/app/infrastructure/config.py backend/tests/unit/test_settings.py && git commit -q -m "$(cat <<'EOF'
feat(alerts): sensor alert bounds in settings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `AlertRepository` — port, in-memory fake, model, migration, SQLAlchemy

**Files:**
- Modify: `backend/src/app/domain/repositories.py`, `backend/src/app/application/ports/unit_of_work.py`, `backend/tests/unit/fakes.py`, `backend/src/app/infrastructure/db/models.py`, `backend/src/app/infrastructure/db/repositories.py`, `backend/src/app/infrastructure/db/unit_of_work.py`
- Create: `backend/alembic/versions/0004_create_alerts.py`
- Test: `backend/tests/integration/test_alert_repository.py`

**Interfaces:**
- Consumes: `Alert`, `Metric` (Task 1).
- Produces: `AlertRepository` ABC (`add`, `save`, `open_for`, `list`, `count_open`), `UnitOfWork.alerts`, `InMemoryAlertRepository` (attribute `alerts: list[Alert]`), `AlertModel`, `SqlAlchemyAlertRepository`, migration `0004`.

- [ ] **Step 1: Write the failing integration tests**

```python
# backend/tests/integration/test_alert_repository.py
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.alert import Alert
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def alert(device="esp-interieur", metric="temperature", minutes=0, resolved=False) -> Alert:
    a = Alert.open(
        device_id=device,
        metric=metric,
        direction="high",
        threshold=30.0,
        at=T0 + timedelta(minutes=minutes),
        value=30.4,
    )
    return a.resolve(at=T0 + timedelta(minutes=minutes + 5), value=29.0) if resolved else a


@pytest.fixture
async def uow(session_factory):
    return SqlAlchemyUnitOfWork(session_factory)


async def seed(uow, alerts):
    async with uow as tx:
        for a in alerts:
            await tx.alerts.add(a)
        await tx.commit()


async def test_open_for_finds_only_the_open_alert_of_that_device_and_metric(uow):
    open_temp = alert()
    await seed(uow, [alert(resolved=True, minutes=-60), open_temp, alert(metric="humidity")])
    async with uow as tx:
        found = await tx.alerts.open_for("esp-interieur", "temperature")
        assert found == open_temp
        assert await tx.alerts.open_for("esp-interieur", "gas") is None
        assert await tx.alerts.open_for("esp-exterieur", "temperature") is None


async def test_save_updates_peak_and_resolution(uow):
    a = alert()
    await seed(uow, [a])
    async with uow as tx:
        await tx.alerts.save(a.worsen(31.5).resolve(at=T0 + timedelta(minutes=9), value=29.0))
        await tx.commit()
    async with uow as tx:
        rows = await tx.alerts.list("all", None, 10)
        assert rows[0].peak_value == 31.5
        assert rows[0].resolved_at == T0 + timedelta(minutes=9)
        assert await tx.alerts.open_for("esp-interieur", "temperature") is None


async def test_list_orders_open_first_then_newest_and_filters(uow):
    old_resolved = alert(minutes=-120, resolved=True)
    new_resolved = alert(minutes=-30, resolved=True, metric="humidity")
    open_now = alert(metric="gas")
    other = alert(device="esp-exterieur", minutes=-10)
    await seed(uow, [old_resolved, new_resolved, open_now, other])
    async with uow as tx:
        everything = await tx.alerts.list("all", None, 10)
        assert [a.id for a in everything] == [open_now.id, other.id, new_resolved.id, old_resolved.id]
        assert [a.id for a in await tx.alerts.list("open", None, 10)] == [open_now.id, other.id]
        assert [a.id for a in await tx.alerts.list("resolved", "esp-interieur", 10)] == [
            new_resolved.id,
            old_resolved.id,
        ]
        assert len(await tx.alerts.list("all", None, 2)) == 2
        assert await tx.alerts.count_open() == 2


async def test_only_one_open_alert_per_device_and_metric(uow):
    await seed(uow, [alert()])
    with pytest.raises(IntegrityError):
        async with uow as tx:
            await tx.alerts.add(alert(minutes=1))
            await tx.commit()
    # A resolved one does not block a new open one.
    async with uow as tx:
        await tx.alerts.save((await tx.alerts.open_for("esp-interieur", "temperature")).resolve(at=T0, value=29.0))
        await tx.alerts.add(alert(minutes=2))
        await tx.commit()
```

Note: `open_for` ordering in `test_list…`: `open_now` (opened at T0) before `other` (opened T0−10 min): both open, newest first → `open_now` then `other`. ✓

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/integration/test_alert_repository.py -q`
Expected: FAIL with `AttributeError: 'SqlAlchemyUnitOfWork' object has no attribute 'alerts'`.

- [ ] **Step 3: Port and unit of work**

Append to `backend/src/app/domain/repositories.py` (import `from typing import Literal` and `from app.domain.alert import Alert, Metric`):

```python
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
    async def list(self, status: AlertStatus, device_id: str | None, limit: int) -> list[Alert]:
        """Open alerts first, then by opened_at descending; at most `limit`."""

    @abstractmethod
    async def count_open(self) -> int: ...
```

In `application/ports/unit_of_work.py`: import `AlertRepository` and add `alerts: AlertRepository` next to `readings`.

In `tests/unit/fakes.py` add (import `Alert`, `Metric` from `app.domain.alert`, `AlertRepository` from `app.domain.repositories`):

```python
class InMemoryAlertRepository(AlertRepository):
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    async def add(self, alert: Alert) -> None:
        self.alerts.append(alert)

    async def save(self, alert: Alert) -> None:
        self.alerts = [alert if a.id == alert.id else a for a in self.alerts]

    async def open_for(self, device_id: str, metric: Metric) -> Alert | None:
        return next(
            (a for a in self.alerts if a.device_id == device_id and a.metric == metric and a.is_open),
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
```

and `self.alerts = InMemoryAlertRepository()` in `InMemoryUnitOfWork.__init__`.

- [ ] **Step 4: Model, migration, SQLAlchemy repository**

`models.py` (import `text` from sqlalchemy):

```python
class AlertModel(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_opened_at", "opened_at"),
        Index(
            "uq_alerts_open_per_metric",
            "device_id",
            "metric",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metric: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(4), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opened_value: Mapped[float] = mapped_column(Float, nullable=False)
    peak_value: Mapped[float] = mapped_column(Float, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_value: Mapped[float | None] = mapped_column(Float, nullable=True)
```

```python
# backend/alembic/versions/0004_create_alerts.py
"""create alerts

One row per out-of-bounds episode of a device metric; at most one open per (device, metric).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("metric", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_value", sa.Float(), nullable=False),
        sa.Column("peak_value", sa.Float(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_value", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_opened_at", "alerts", ["opened_at"])
    op.create_index(
        "uq_alerts_open_per_metric",
        "alerts",
        ["device_id", "metric"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_alerts_open_per_metric", table_name="alerts")
    op.drop_index("ix_alerts_opened_at", table_name="alerts")
    op.drop_table("alerts")
```

`infrastructure/db/repositories.py` (imports: `AlertRepository, AlertStatus` from domain.repositories, `Alert, Metric` from domain.alert, `AlertModel`, and `cast` from typing for the Literal columns):

```python
def _alert_to_entity(row: AlertModel) -> Alert:
    return Alert(
        id=row.id,
        device_id=row.device_id,
        metric=cast(Metric, row.metric),
        direction=cast(Direction, row.direction),
        threshold=row.threshold,
        opened_at=row.opened_at,
        opened_value=row.opened_value,
        peak_value=row.peak_value,
        resolved_at=row.resolved_at,
        resolved_value=row.resolved_value,
    )


class SqlAlchemyAlertRepository(AlertRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, alert: Alert) -> None:
        self._session.add(
            AlertModel(
                id=alert.id,
                device_id=alert.device_id,
                metric=alert.metric,
                direction=alert.direction,
                threshold=alert.threshold,
                opened_at=alert.opened_at,
                opened_value=alert.opened_value,
                peak_value=alert.peak_value,
                resolved_at=alert.resolved_at,
                resolved_value=alert.resolved_value,
            )
        )
        await self._session.flush()

    async def save(self, alert: Alert) -> None:
        row = await self._session.get(AlertModel, alert.id)
        if row is None:
            raise LookupError(f"alert {alert.id} not found")
        row.peak_value = alert.peak_value
        row.resolved_at = alert.resolved_at
        row.resolved_value = alert.resolved_value
        await self._session.flush()

    async def open_for(self, device_id: str, metric: Metric) -> Alert | None:
        m = AlertModel
        stmt = select(m).where(m.device_id == device_id, m.metric == metric, m.resolved_at.is_(None))
        row = (await self._session.scalars(stmt)).first()
        return _alert_to_entity(row) if row else None

    async def list(self, status: AlertStatus, device_id: str | None, limit: int) -> list[Alert]:
        m = AlertModel
        stmt = select(m)
        if device_id is not None:
            stmt = stmt.where(m.device_id == device_id)
        if status == "open":
            stmt = stmt.where(m.resolved_at.is_(None))
        elif status == "resolved":
            stmt = stmt.where(m.resolved_at.is_not(None))
        stmt = stmt.order_by(m.resolved_at.is_(None).desc(), m.opened_at.desc()).limit(limit)
        return [_alert_to_entity(r) for r in (await self._session.scalars(stmt)).all()]

    async def count_open(self) -> int:
        m = AlertModel
        stmt = select(func.count()).select_from(m).where(m.resolved_at.is_(None))
        return int((await self._session.execute(stmt)).scalar_one())
```

`add` flushes so the partial unique index raises at `add`/`commit` time inside the transaction (the test expects `IntegrityError` out of the `async with` block: flush raises inside, `__aexit__` rolls back and the exception propagates). Import `Direction` too.

`infrastructure/db/unit_of_work.py`: `self.alerts = SqlAlchemyAlertRepository(self._session)` in `__aenter__`.

- [ ] **Step 5: Run all backend tests**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run alembic upgrade head 2>&1 | tail -1; uv run ruff check . && uv run ruff format --check . && uv run pytest -q 2>&1 | tail -2`
Expected: migration applies to the dev DB (`Running upgrade 0003 -> 0004`), ruff clean, all tests pass (`test_alert_repository` 4 passed; the integration conftest recreates the schema from `Base.metadata`, so the model and the migration must agree).

- [ ] **Step 6: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend && git commit -q -m "$(cat <<'EOF'
feat(alerts): alert repository, table and migration, one open alert per device metric

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `RecordReading` opens, worsens and resolves alerts; wiring

**Files:**
- Create: `backend/src/app/application/alerts/__init__.py`, `backend/src/app/application/alerts/dtos.py`
- Modify: `backend/src/app/application/sensors/record.py`, `backend/src/app/infrastructure/mqtt/subscriber.py`, `backend/src/app/presentation/http/sensors.py`, `backend/src/app/presentation/dependencies.py`, `backend/src/app/presentation/main.py`
- Test: `backend/tests/unit/test_record_reading.py` (append)

**Interfaces:**
- Consumes: domain (Task 1), `UnitOfWork.alerts` (Task 3), `Settings.thresholds()` (Task 2).
- Produces: `AlertOutput.from_entity(alert)`, `AlertOutput.to_event() -> dict` (`id` str, dates `…Z` or None); `RecordReading(uow, broadcaster, thresholds=DEFAULT_THRESHOLDS, clock=None)`; `MqttSubscriber(..., thresholds=DEFAULT_THRESHOLDS)`; `app.state.thresholds`; `ThresholdsDep`.

- [ ] **Step 1: Write the failing tests** (append to `test_record_reading.py`; add `from app.domain.alert import Thresholds` and `from datetime import …` already present)

```python
def events_of(bus, kind):
    return [e for e in bus.events if e["type"] == kind]


async def test_out_of_bounds_reading_opens_an_alert_after_the_reading_event():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    await RecordReading(uow, bus, clock=lambda: NOW).execute(make_input(temperature_c=30.4))
    assert [e["type"] for e in bus.events] == ["sensor.reading", "alert.opened"]
    opened = bus.events[1]["data"]
    assert (opened["metric"], opened["direction"], opened["threshold"]) == ("temperature", "high", 30.0)
    assert opened["opened_at"] == "2026-10-06T09:00:00Z"
    assert opened["resolved_at"] is None
    assert len(uow.alerts.alerts) == 1 and uow.alerts.alerts[0].is_open


async def test_a_worse_reading_updates_the_peak_without_an_event():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    use_case = RecordReading(uow, bus, clock=lambda: NOW)
    await use_case.execute(make_input(temperature_c=30.4))
    await use_case.execute(make_input(temperature_c=31.2))
    assert len(events_of(bus, "alert.opened")) == 1
    assert len(uow.alerts.alerts) == 1
    assert uow.alerts.alerts[0].peak_value == 31.2


async def test_just_under_the_bound_keeps_the_alert_open():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    use_case = RecordReading(uow, bus, clock=lambda: NOW)
    await use_case.execute(make_input(temperature_c=30.4))
    await use_case.execute(make_input(temperature_c=29.8))
    assert events_of(bus, "alert.resolved") == []
    assert uow.alerts.alerts[0].is_open


async def test_back_under_the_margin_resolves_with_the_reading_time_and_value():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    use_case = RecordReading(uow, bus, clock=lambda: NOW)
    await use_case.execute(make_input(temperature_c=30.4))
    later = NOW + timedelta(minutes=4)
    await use_case.execute(make_input(temperature_c=29.4, recorded_at=later))
    resolved = events_of(bus, "alert.resolved")
    assert len(resolved) == 1
    assert resolved[0]["data"]["resolved_at"] == "2026-10-06T09:04:00Z"
    assert resolved[0]["data"]["resolved_value"] == 29.4
    assert not uow.alerts.alerts[0].is_open


async def test_missing_value_changes_nothing():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    use_case = RecordReading(uow, bus, clock=lambda: NOW)
    await use_case.execute(make_input(temperature_c=30.4))
    await use_case.execute(make_input(temperature_c=None))
    assert [e["type"] for e in bus.events] == ["sensor.reading", "alert.opened", "sensor.reading"]
    assert uow.alerts.alerts[0].is_open


async def test_two_metrics_out_of_bounds_open_two_alerts():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    await RecordReading(uow, bus, clock=lambda: NOW).execute(
        make_input(temperature_c=31.0, gas_level=1800, gas_alert=True)
    )
    assert [e["data"]["metric"] for e in events_of(bus, "alert.opened")] == ["temperature", "gas"]


async def test_custom_thresholds_are_honoured():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    t = Thresholds(temperature=(10.0, 25.0), humidity=(20.0, 70.0), gas_max=None)
    await RecordReading(uow, bus, thresholds=t, clock=lambda: NOW).execute(make_input(temperature_c=26.0))
    assert len(events_of(bus, "alert.opened")) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_record_reading.py -q`
Expected: the 7 new tests FAIL (`alert.opened` never emitted, `uow.alerts.alerts` empty); the 4 old ones still pass.

- [ ] **Step 3: DTO**

```python
# backend/src/app/application/alerts/__init__.py
# (empty)
```

```python
# backend/src/app/application/alerts/dtos.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domain.alert import Alert, Direction, Metric


def _iso_z(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class AlertOutput:
    id: UUID
    device_id: str
    metric: Metric
    direction: Direction
    threshold: float
    opened_at: datetime
    opened_value: float
    peak_value: float
    resolved_at: datetime | None
    resolved_value: float | None

    @classmethod
    def from_entity(cls, alert: Alert) -> AlertOutput:
        return cls(**{f: getattr(alert, f) for f in cls.__dataclass_fields__})

    def to_event(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = str(self.id)
        data["opened_at"] = _iso_z(self.opened_at)
        data["resolved_at"] = _iso_z(self.resolved_at)
        return data
```

- [ ] **Step 4: Use case**

In `record.py`: imports `from app.application.alerts.dtos import AlertOutput` and `from app.domain.alert import DEFAULT_THRESHOLDS, METRICS, Alert, Thresholds, back_in_range, violations`. Constructor gains `thresholds: Thresholds = DEFAULT_THRESHOLDS` (keyword, before `clock`), stored as `self._thresholds`. Replace the body of `execute` from `async with` onwards:

```python
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

    async def _apply_alerts(self, uow: UnitOfWork, reading: SensorReading) -> list[tuple[str, Alert]]:
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
                value = _metric_value(reading, metric)
                resolved = current.resolve(at=reading.recorded_at, value=value)
                await uow.alerts.save(resolved)
                events.append(("alert.resolved", resolved))
        return events


def _metric_value(reading: SensorReading, metric: str) -> float:
    if metric == "temperature":
        return float(reading.temperature_c or 0.0)
    if metric == "humidity":
        return float(reading.humidity_pct or 0.0)
    return float(reading.gas_level or 0)
```

(`back_in_range` returns False on a missing value, so `_metric_value`'s `or 0.0` is only a type guard.)

- [ ] **Step 5: Wiring**

- `presentation/dependencies.py`: `def get_thresholds(conn: HTTPConnection) -> Thresholds: return conn.app.state.thresholds` and `ThresholdsDep = Annotated[Thresholds, Depends(get_thresholds)]` (import `Thresholds` from `app.domain.alert`).
- `presentation/http/sensors.py`: `post_reading(body, _: DeviceKeyDep, uow: UowDep, hub: HubDep, thresholds: ThresholdsDep)` → `RecordReading(uow=uow, broadcaster=hub, thresholds=thresholds)`.
- `infrastructure/mqtt/subscriber.py`: constructor param `thresholds: Thresholds = DEFAULT_THRESHOLDS` stored and passed: `RecordReading(self._uow_factory(), self._broadcaster, thresholds=self._thresholds)`.
- `presentation/main.py`: `app.state.thresholds = settings.thresholds()` after `app.state.settings`; `_start_mqtt_subscriber` passes `thresholds=app.state.thresholds`.

- [ ] **Step 6: Run the backend suite**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q 2>&1 | tail -1`
Expected: all pass (previous + 7).

- [ ] **Step 7: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend && git commit -q -m "$(cat <<'EOF'
feat(alerts): RecordReading opens, worsens and resolves alerts in the reading's transaction

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Routes `GET /alerts` and `GET /alerts/summary`

**Files:**
- Create: `backend/src/app/presentation/http/alerts.py`
- Modify: `backend/src/app/presentation/main.py` (include router)
- Test: `backend/tests/integration/test_alerts_http.py`

**Interfaces:**
- Consumes: `UowDep`, `CurrentUserIdDep`, `AlertOutput` (Task 4), `AlertStatus` (Task 3).
- Produces: `GET /alerts?status&device_id&limit` → `list[AlertResponse]`; `GET /alerts/summary` → `{"open": int}`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/integration/test_alerts_http.py
from tests.integration.conftest import DEVICE_HEADERS, create_user_and_login

NORMAL = {"device_id": "esp-interieur", "temperature": {"humidity": 48.0, "temp": 22.0}}
HOT = {"device_id": "esp-interieur", "temperature": {"humidity": 48.0, "temp": 30.4}}
COOL = {"device_id": "esp-interieur", "temperature": {"humidity": 48.0, "temp": 29.0}}


def auth(client):
    return {"Authorization": f"Bearer {create_user_and_login(client)['access_token']}"}


def test_alerts_require_a_token(client):
    assert client.get("/alerts").status_code == 401
    assert client.get("/alerts/summary").status_code == 401


def test_alerts_open_then_resolve_through_readings(client):
    headers = auth(client)
    assert client.get("/alerts", headers=headers).json() == []
    assert client.get("/alerts/summary", headers=headers).json() == {"open": 0}

    assert client.post("/sensors/readings", json=HOT, headers=DEVICE_HEADERS).status_code == 201
    alerts = client.get("/alerts", headers=headers).json()
    assert len(alerts) == 1
    assert (alerts[0]["metric"], alerts[0]["direction"], alerts[0]["threshold"]) == ("temperature", "high", 30.0)
    assert alerts[0]["resolved_at"] is None
    assert client.get("/alerts/summary", headers=headers).json() == {"open": 1}
    assert client.get("/alerts?status=resolved", headers=headers).json() == []

    assert client.post("/sensors/readings", json=COOL, headers=DEVICE_HEADERS).status_code == 201
    resolved = client.get("/alerts?status=resolved&device_id=esp-interieur", headers=headers).json()
    assert len(resolved) == 1 and resolved[0]["resolved_value"] == 29.0
    assert client.get("/alerts?status=open", headers=headers).json() == []
    assert client.get("/alerts?device_id=esp-exterieur", headers=headers).json() == []


def test_alert_events_follow_the_reading_event_on_the_websocket(client):
    tokens = create_user_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        client.post("/sensors/readings", json=HOT, headers=DEVICE_HEADERS)
        assert ws.receive_json()["type"] == "sensor.reading"
        opened = ws.receive_json()
        assert opened["type"] == "alert.opened"
        assert opened["data"]["opened_at"].endswith("Z")
        client.post("/sensors/readings", json=COOL, headers=DEVICE_HEADERS)
        assert ws.receive_json()["type"] == "sensor.reading"
        assert ws.receive_json()["type"] == "alert.resolved"


def test_limit_is_validated(client):
    headers = auth(client)
    assert client.get("/alerts?limit=0", headers=headers).status_code == 422
    assert client.get("/alerts?status=bogus", headers=headers).status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/integration/test_alerts_http.py -q`
Expected: FAIL with 404s (`assert 404 == 401` on the first test).

- [ ] **Step 3: Implement**

```python
# backend/src/app/presentation/http/alerts.py
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.application.alerts.dtos import AlertOutput
from app.domain.alert import Alert, Direction, Metric
from app.domain.repositories import AlertStatus
from app.presentation.dependencies import CurrentUserIdDep, UowDep

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertResponse(BaseModel):
    id: UUID
    device_id: str
    metric: Metric
    direction: Direction
    threshold: float
    opened_at: datetime
    opened_value: float
    peak_value: float
    resolved_at: datetime | None
    resolved_value: float | None

    @classmethod
    def from_entity(cls, alert: Alert) -> "AlertResponse":
        return cls(**AlertOutput.from_entity(alert).to_event())


class AlertSummary(BaseModel):
    open: int = Field(ge=0)


@router.get(
    "",
    response_model=list[AlertResponse],
    summary="Alertes capteurs : ouvertes d'abord, puis les plus récentes",
    description="Une alerte s'ouvre quand une mesure sort des bornes (réglages `ALERT_*`) et se "
    "ferme seule quand la mesure revient dans les bornes, avec hystérésis.",
)
async def list_alerts(
    _: CurrentUserIdDep,
    uow: UowDep,
    status: Annotated[AlertStatus, Query()] = "all",
    device_id: Annotated[str | None, Query(pattern=r"^[a-z0-9-]{1,64}$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlertResponse]:
    async with uow as tx:
        alerts = await tx.alerts.list(status, device_id, limit)
    return [AlertResponse.from_entity(a) for a in alerts]


@router.get("/summary", response_model=AlertSummary, summary="Nombre d'alertes ouvertes")
async def alert_summary(_: CurrentUserIdDep, uow: UowDep) -> AlertSummary:
    async with uow as tx:
        return AlertSummary(open=await tx.alerts.count_open())
```

`main.py`: import `alerts` in the `presentation.http` import line and `app.include_router(alerts.router)` after `sensors`.

- [ ] **Step 4: Run the backend suite**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q 2>&1 | tail -1`
Expected: all pass (previous + 4).

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend && git commit -q -m "$(cat <<'EOF'
feat(alerts): GET /alerts with status and device filters, GET /alerts/summary

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Simulator `--spike`

**Files:**
- Modify: `backend/src/app/presentation/simulate.py`
- Test: `backend/tests/unit/test_simulate_sensors.py` (append)

**Interfaces:**
- Produces: `SensorWalk.next_payload(device_id, spike: str | None = None)`; `run(..., spike: str | None = None)` posting 16 readings (5 normal, 6 spiked, 5 normal) then returning; CLI `--spike` and `--spike-metric {temperature,humidity,gas}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_spike_overrides_one_metric():
    walk = SensorWalk(random.Random(3))
    assert walk.next_payload("esp-interieur", spike="temperature")["temperature"]["temp"] == 33.0
    assert walk.next_payload("esp-interieur", spike="humidity")["temperature"]["humidity"] == 78.0
    gas = walk.next_payload("esp-interieur", spike="gas")["gaz"]
    assert gas["mostGaz"] is True and gas["quantity"] >= 1600


def test_run_with_spike_posts_five_normal_six_hot_five_normal_then_stops():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"ok": True})

    sent = run(
        base_url="http://api.test",
        device_key="k" * 16,
        device_id="esp-interieur",
        interval=0,
        count=None,
        transport=httpx.MockTransport(handler),
        log=lambda _: None,
        spike="temperature",
    )
    assert sent == 16
    temps = [b["temperature"]["temp"] for b in bodies]
    assert all(t == 33.0 for t in temps[5:11])
    assert all(t < 33.0 for t in temps[:5] + temps[11:])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_simulate_sensors.py -q`
Expected: 2 FAIL (`TypeError: … unexpected keyword argument 'spike'`).

- [ ] **Step 3: Implement**

In `SensorWalk.next_payload(self, device_id, spike: str | None = None)`: build `payload` as today, then before `return`:

```python
        if spike == "temperature":
            payload["temperature"]["temp"] = 33.0
        elif spike == "humidity":
            payload["temperature"]["humidity"] = 78.0
        elif spike == "gas":
            payload["gaz"] = {"mostGaz": True, "quantity": max(quantity, 1600)}
```

In `run(...)`, add the parameter `spike: str | None = None` and, before the live loop:

```python
        if spike is not None:
            # 5 normal readings, 6 out of bounds, 5 normal: one alert opens, then resolves.
            for i in range(16):
                payload = walk.next_payload(device_id, spike if 5 <= i < 11 else None)
                response = client.post("/sensors/readings", json=payload, headers=headers)
                if response.status_code != 201:
                    log(f"refusé ({response.status_code}) : {response.text}")
                    return sent
                sent += 1
                log(f"{device_id}: {'HORS BORNES' if 5 <= i < 11 else 'normal'} {payload['temperature']}")
                if i < 15:
                    time.sleep(interval)
            return sent
```

CLI: `parser.add_argument("--spike", action="store_true", help="5 mesures normales, 6 hors bornes, 5 normales, puis quitte")`, `parser.add_argument("--spike-metric", choices=("temperature", "humidity", "gas"), default="temperature")`; pass `spike=args.spike_metric if args.spike else None`. Update the module docstring with the two flags.

- [ ] **Step 4: Run the unit suite**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run ruff check . && uv run ruff format --check . && uv run pytest tests/unit -q 2>&1 | tail -1`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend && git commit -q -m "$(cat <<'EOF'
feat(simulate): --spike sends an out-of-bounds burst to see an alert open and resolve

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Front helpers, fixtures, MSW handlers

**Files:**
- Create: `frontend/src/features/alerts/alerts-api.ts`, `frontend/src/test/alerts.ts`
- Modify: `frontend/src/test/server.ts`
- Test: `frontend/src/features/alerts/alerts-api.test.ts`

**Interfaces:**
- Produces: types `Metric`, `Direction`, `Alert`; `ALERTS_PATH`, `ALERTS_SUMMARY_PATH`, `ALERTS_LIMIT = 200`, `alertsPath(limit)`; `METRIC_LABELS`, `UNITS`, `DIGITS`; `isOpen(a)`, `describeAlert(a)`, `sortAlerts(list)`, `upsert(list, a)`, `formatDuration(ms)`, `durationLabel(a, nowMs)`. Fixtures: `makeAlert(overrides)`, `ALERTS_NOW_MS`, `alertsFixture()` (one resolved humidity alert; no open one by default). MSW: `GET /api/alerts` (honours `status`, `device_id`, `limit`), `GET /api/alerts/summary`.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/features/alerts/alerts-api.test.ts
import { describe, expect, it } from "vitest";
import { ALERTS_NOW_MS, makeAlert } from "@/test/alerts";
import { formatNumber } from "@/lib/format-number";
import { describeAlert, durationLabel, formatDuration, sortAlerts, upsert } from "./alerts-api";

describe("alerts api helpers", () => {
  it("describes an alert with its peak and its bound", () => {
    expect(describeAlert(makeAlert())).toBe("Température 31,2 °C > 30 °C");
    expect(
      describeAlert(makeAlert({ metric: "humidity", direction: "low", threshold: 20, peak_value: 12 })),
    ).toBe("Humidité 12 % < 20 %");
    expect(describeAlert(makeAlert({ metric: "gas", threshold: 1500, peak_value: 1800 }))).toBe(
      `Gaz ${formatNumber(1800, 0)} mV > ${formatNumber(1500, 0)} mV`,
    );
    expect(describeAlert(makeAlert({ metric: "gas", threshold: 0, peak_value: 1800 }))).toBe(
      "Gaz : alerte ESP",
    );
  });

  it("formats durations in French", () => {
    expect(formatDuration(30_000)).toBe("moins d'une minute");
    expect(formatDuration(4 * 60_000)).toBe("4 min");
    expect(formatDuration(2 * 3_600_000 + 5 * 60_000)).toBe("2 h 05");
    expect(formatDuration(27 * 3_600_000)).toBe("1 j 3 h");
  });

  it("labels open alerts with « depuis » and resolved ones with their total duration", () => {
    const open = makeAlert({ opened_at: new Date(ALERTS_NOW_MS - 4 * 60_000).toISOString() });
    expect(durationLabel(open, ALERTS_NOW_MS)).toBe("depuis 4 min");
    const resolved = makeAlert({
      opened_at: new Date(ALERTS_NOW_MS - 20 * 60_000).toISOString(),
      resolved_at: new Date(ALERTS_NOW_MS - 8 * 60_000).toISOString(),
      resolved_value: 29.1,
    });
    expect(durationLabel(resolved, ALERTS_NOW_MS)).toBe("12 min");
  });

  it("sorts open alerts first, then newest first", () => {
    const oldResolved = makeAlert({ id: "a", opened_at: "2026-10-06T07:00:00Z", resolved_at: "2026-10-06T07:10:00Z" });
    const newResolved = makeAlert({ id: "b", opened_at: "2026-10-06T08:00:00Z", resolved_at: "2026-10-06T08:10:00Z" });
    const open = makeAlert({ id: "c", opened_at: "2026-10-06T06:00:00Z" });
    expect(sortAlerts([oldResolved, newResolved, open]).map((a) => a.id)).toEqual(["c", "b", "a"]);
  });

  it("upserts by id and keeps an unknown resolved alert", () => {
    const open = makeAlert({ id: "x" });
    const list = upsert([], open);
    const resolved = { ...open, resolved_at: "2026-10-06T09:05:00Z", resolved_value: 29 };
    expect(upsert(list, resolved)).toEqual([resolved]);
    const stranger = makeAlert({ id: "y", resolved_at: "2026-10-06T09:06:00Z" });
    expect(upsert(list, stranger).map((a) => a.id)).toEqual(["x", "y"]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/alerts/alerts-api.test.ts`
Expected: FAIL (`Failed to resolve import "@/test/alerts"`).

- [ ] **Step 3: Implement**

```ts
// frontend/src/features/alerts/alerts-api.ts
import { formatNumber } from "@/lib/format-number";

export type Metric = "temperature" | "humidity" | "gas";
export type Direction = "low" | "high";

export type Alert = {
  id: string;
  device_id: string;
  metric: Metric;
  direction: Direction;
  threshold: number;
  opened_at: string;
  opened_value: number;
  peak_value: number;
  resolved_at: string | null;
  resolved_value: number | null;
};

export const ALERTS_PATH = "/alerts";
export const ALERTS_SUMMARY_PATH = "/alerts/summary";
export const ALERTS_LIMIT = 200;

export function alertsPath(limit = ALERTS_LIMIT): string {
  return `${ALERTS_PATH}?limit=${limit}`;
}

export const METRIC_LABELS: Record<Metric, string> = {
  temperature: "Température",
  humidity: "Humidité",
  gas: "Gaz",
};
export const UNITS: Record<Metric, string> = { temperature: "°C", humidity: "%", gas: "mV" };
export const DIGITS: Record<Metric, number> = { temperature: 1, humidity: 0, gas: 0 };

export function isOpen(alert: Alert): boolean {
  return alert.resolved_at === null;
}

/** « Température 31,2 °C > 30 °C » — or « Gaz : alerte ESP » when only the device flag spoke. */
export function describeAlert(alert: Alert): string {
  if (alert.metric === "gas" && alert.threshold === 0) return "Gaz : alerte ESP";
  const unit = UNITS[alert.metric];
  const digits = DIGITS[alert.metric];
  const sign = alert.direction === "high" ? ">" : "<";
  return `${METRIC_LABELS[alert.metric]} ${formatNumber(alert.peak_value, digits)} ${unit} ${sign} ${formatNumber(alert.threshold, digits)} ${unit}`;
}

export function sortAlerts(alerts: Alert[]): Alert[] {
  return [...alerts].sort((a, b) => {
    if (isOpen(a) !== isOpen(b)) return isOpen(a) ? -1 : 1;
    return Date.parse(b.opened_at) - Date.parse(a.opened_at);
  });
}

/** Replace the alert with the same id, or add it; always returns a sorted copy. */
export function upsert(alerts: Alert[], alert: Alert): Alert[] {
  const others = alerts.filter((a) => a.id !== alert.id);
  return sortAlerts([...others, alert]);
}

export function formatDuration(ms: number): string {
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "moins d'une minute";
  const hours = Math.floor(minutes / 60);
  if (hours < 1) return `${minutes} min`;
  const days = Math.floor(hours / 24);
  if (days < 1) return `${hours} h ${String(minutes % 60).padStart(2, "0")}`;
  return `${days} j ${hours % 24} h`;
}

export function durationLabel(alert: Alert, nowMs: number): string {
  const opened = Date.parse(alert.opened_at);
  if (alert.resolved_at === null) return `depuis ${formatDuration(nowMs - opened)}`;
  return formatDuration(Date.parse(alert.resolved_at) - opened);
}
```

```ts
// frontend/src/test/alerts.ts
import type { Alert } from "@/features/alerts/alerts-api";

export const ALERTS_NOW_MS = Date.UTC(2026, 9, 6, 9, 0, 0);

export function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: "alert-1",
    device_id: "esp-interieur",
    metric: "temperature",
    direction: "high",
    threshold: 30,
    opened_at: new Date(ALERTS_NOW_MS - 4 * 60_000).toISOString(),
    opened_value: 30.4,
    peak_value: 31.2,
    resolved_at: null,
    resolved_value: null,
    ...overrides,
  };
}

/** Default API state in tests: one resolved humidity alert, nothing open. */
export function alertsFixture(): Alert[] {
  return [
    makeAlert({
      id: "alert-resolved",
      metric: "humidity",
      direction: "high",
      threshold: 70,
      opened_value: 71,
      peak_value: 74,
      opened_at: new Date(ALERTS_NOW_MS - 60 * 60_000).toISOString(),
      resolved_at: new Date(ALERTS_NOW_MS - 48 * 60_000).toISOString(),
      resolved_value: 67,
    }),
  ];
}
```

In `frontend/src/test/server.ts`, import `{ alertsFixture } from "./alerts"` and add two handlers (after the server health one):

```ts
  http.get("/api/alerts", ({ request }) => {
    if (!isValidAccessToken(bearer(request))) return unauthenticated();
    const url = new URL(request.url);
    const status = url.searchParams.get("status") ?? "all";
    const device = url.searchParams.get("device_id");
    const limit = Number(url.searchParams.get("limit") ?? 100);
    const rows = alertsFixture()
      .filter((a) => (device ? a.device_id === device : true))
      .filter((a) => status === "all" || (status === "open") === (a.resolved_at === null));
    return HttpResponse.json(rows.slice(0, limit));
  }),
  http.get("/api/alerts/summary", ({ request }) =>
    isValidAccessToken(bearer(request))
      ? HttpResponse.json({ open: alertsFixture().filter((a) => a.resolved_at === null).length })
      : unauthenticated(),
  ),
```

- [ ] **Step 4: Toolchain**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | grep -E "Tests |×"`
Expected: all pass (previous 123 + 5).

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src/features/alerts frontend/src/test && git commit -q -m "$(cat <<'EOF'
feat(frontend): alert types, description and duration helpers, test fixtures

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: `useAlerts` and `useAlertCount`

**Files:**
- Create: `frontend/src/features/alerts/use-alerts.ts`, `frontend/src/features/alerts/use-alert-count.ts`
- Test: `frontend/src/features/alerts/use-alerts.test.tsx`

**Interfaces:**
- Consumes: `useEventStream`, helpers (Task 7).
- Produces: `useAlerts(enabled = true): { status: "loading" | "ready" | "error"; alerts: Alert[]; open: Alert[]; connected: boolean }`; `useAlertCount(): number | null` (open count from `/alerts/summary`, +1 on `alert.opened`, −1 on `alert.resolved`, floor 0).

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/alerts/use-alerts.test.tsx
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { makeAlert } from "@/test/alerts";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import { useAlertCount } from "./use-alert-count";
import { useAlerts } from "./use-alerts";

function Probe() {
  const { status, alerts, open } = useAlerts();
  const count = useAlertCount();
  return (
    <div>
      <p>status:{status}</p>
      <p>total:{alerts.length}</p>
      <p>open:{open.length}</p>
      <p>ids:{alerts.map((a) => a.id).join(",")}</p>
      <p>count:{count ?? "-"}</p>
    </div>
  );
}

function renderProbe() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe("useAlerts / useAlertCount", () => {
  it("loads the list and the count", async () => {
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("total:1")).toBeInTheDocument();
    expect(screen.getByText("open:0")).toBeInTheDocument();
    expect(await screen.findByText("count:0")).toBeInTheDocument();
  });

  it("adds on alert.opened, replaces on alert.resolved, keeps the count in step", async () => {
    // Two hooks → two sockets: every connected client must receive each event.
    const clients: { send(data: string): void }[] = [];
    const send = (data: string) => clients.forEach((c) => c.send(data));
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        clients.push(client);
      }),
    );
    renderProbe();
    await screen.findByText("status:ready");
    await screen.findByText("count:0");
    await wait(50);
    const opened = makeAlert({ id: "new" });
    send(JSON.stringify({ type: "alert.opened", data: opened }));
    expect(await screen.findByText("open:1")).toBeInTheDocument();
    expect(screen.getByText("ids:new,alert-resolved")).toBeInTheDocument();
    expect(screen.getByText("count:1")).toBeInTheDocument();
    send(
      JSON.stringify({
        type: "alert.resolved",
        data: { ...opened, resolved_at: "2026-10-06T09:05:00Z", resolved_value: 29 },
      }),
    );
    expect(await screen.findByText("open:0")).toBeInTheDocument();
    expect(screen.getByText("total:2")).toBeInTheDocument();
    expect(screen.getByText("count:0")).toBeInTheDocument();
  });

  it("recovers from a failed list request on the first event", async () => {
    server.use(
      http.get("/api/alerts", () => HttpResponse.error()),
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(JSON.stringify({ type: "alert.opened", data: makeAlert({ id: "late" }) }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("ids:late")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/alerts/use-alerts.test.tsx`
Expected: FAIL (`Failed to resolve import "./use-alert-count"`).

- [ ] **Step 3: Implement**

```ts
// frontend/src/features/alerts/use-alerts.ts
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { useEventStream } from "@/features/realtime/use-event-stream";
import { alertsPath, isOpen, sortAlerts, upsert, type Alert } from "./alerts-api";

type Status = "loading" | "ready" | "error";

/** The alert list, kept live by `alert.opened` / `alert.resolved` events. */
export function useAlerts(enabled = true) {
  const { authFetch } = useAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [alerts, setAlerts] = useState<Alert[]>([]);
  // Events that arrive before the list response; merged once it lands.
  const pending = useRef<Alert[]>([]);
  const loaded = useRef(false);
  const failed = useRef(false);

  useEffect(() => {
    let cancelled = false;
    loaded.current = false;
    failed.current = false;
    authFetch<Alert[]>(alertsPath())
      .then((list) => {
        if (cancelled) return;
        const merged = pending.current.reduce((acc, a) => upsert(acc, a), sortAlerts(list));
        pending.current = [];
        loaded.current = true;
        setAlerts(merged);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        failed.current = true;
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  const onEvent = useCallback((type: string, data: unknown) => {
    if ((type !== "alert.opened" && type !== "alert.resolved") || !data) return;
    const alert = data as Alert;
    if (!loaded.current && !failed.current) {
      pending.current = upsert(pending.current, alert);
      return;
    }
    if (failed.current) {
      failed.current = false;
      loaded.current = true;
      const seeded = upsert(pending.current, alert);
      pending.current = [];
      setAlerts(seeded);
      setStatus("ready");
      return;
    }
    setAlerts((current) => upsert(current, alert));
  }, []);
  const { connected } = useEventStream(enabled, onEvent);

  return { status, alerts, open: alerts.filter(isOpen), connected };
}
```

```ts
// frontend/src/features/alerts/use-alert-count.ts
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { useEventStream } from "@/features/realtime/use-event-stream";
import { ALERTS_SUMMARY_PATH } from "./alerts-api";

/** Number of open alerts for the nav badge; null until the summary has loaded. */
export function useAlertCount(): number | null {
  const { authFetch } = useAuth();
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    authFetch<{ open: number }>(ALERTS_SUMMARY_PATH)
      .then((summary) => {
        if (!cancelled) setCount(summary.open);
      })
      .catch(() => {
        // Keep whatever we had; the next event will adjust it.
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  const onEvent = useCallback((type: string) => {
    if (type === "alert.opened") setCount((c) => (c ?? 0) + 1);
    if (type === "alert.resolved") setCount((c) => Math.max(0, (c ?? 1) - 1));
  }, []);
  useEventStream(true, onEvent);

  return count;
}
```

- [ ] **Step 4: Toolchain**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | grep -E "Tests |×"`
Expected: all pass (+3).

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src/features/alerts && git commit -q -m "$(cat <<'EOF'
feat(frontend): useAlerts and useAlertCount follow alert.opened / alert.resolved

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: `AlertRow` and `AlertsCard`

**Files:**
- Create: `frontend/src/features/alerts/alert-row.tsx`, `frontend/src/features/alerts/alerts-card.tsx`
- Test: `frontend/src/features/alerts/alerts-card.test.tsx`

**Interfaces:**
- Consumes: helpers (Task 7). The card takes data by props (the Dashboard mounts `useAlerts` once).
- Produces: `AlertRow({ alert, nowMs })` (`<li>`); `AlertsCard({ status, alerts, nowMs?, className? })` — a `Link to="/alertes"` with `aria-label="Alertes, voir l'historique"`; `RESOLVED_SHOWN = 5`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/alerts/alerts-card.test.tsx
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderRoutes } from "@/test/render";
import { ALERTS_NOW_MS, makeAlert } from "@/test/alerts";
import type { Alert } from "./alerts-api";
import { AlertsCard } from "./alerts-card";

const LINK = "Alertes, voir l'historique";

function renderCard(alerts: Alert[], status: "loading" | "ready" | "error" = "ready") {
  return renderRoutes([
    { path: "/", element: <AlertsCard status={status} alerts={alerts} nowMs={ALERTS_NOW_MS} /> },
    { path: "/alertes", element: <h1>Alertes</h1> },
  ]);
}

describe("AlertsCard", () => {
  it("links to the alerts page and counts the open ones", async () => {
    renderCard([makeAlert({ id: "a" }), makeAlert({ id: "b", metric: "gas", threshold: 0 })]);
    const link = screen.getByRole("link", { name: LINK });
    expect(link).toHaveAttribute("href", "/alertes");
    expect(within(link).getByText("2 ouvertes")).toBeInTheDocument();
    const items = within(link).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Ouverte");
    expect(items[0]).toHaveTextContent("esp-interieur");
    expect(items[0]).toHaveTextContent("Température 31,2 °C > 30 °C");
    expect(items[0]).toHaveTextContent("depuis 4 min");
    expect(items[1]).toHaveTextContent("Gaz : alerte ESP");
  });

  it("shows « Aucune alerte » and at most five resolved ones", () => {
    const resolved = Array.from({ length: 7 }, (_, i) =>
      makeAlert({
        id: `r${i}`,
        opened_at: new Date(ALERTS_NOW_MS - (i + 2) * 60_000).toISOString(),
        resolved_at: new Date(ALERTS_NOW_MS - (i + 1) * 60_000).toISOString(),
        resolved_value: 29,
      }),
    );
    renderCard(resolved);
    const link = screen.getByRole("link", { name: LINK });
    expect(within(link).getByText("Aucune alerte")).toBeInTheDocument();
    const items = within(link).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent("Résolue");
    expect(items[0]).toHaveTextContent("1 min");
  });

  it("shows a skeleton while loading and a message on error", () => {
    const { unmount } = renderCard([], "loading");
    expect(screen.getByRole("status", { name: "Chargement des alertes" })).toBeInTheDocument();
    unmount();
    renderCard([], "error");
    expect(screen.getByText("Alertes indisponibles")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/alerts/alerts-card.test.tsx`
Expected: FAIL (`Failed to resolve import "./alerts-card"`).

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/alerts/alert-row.tsx
import { formatTime } from "@/lib/format-number";
import { cn } from "@/lib/utils";
import { describeAlert, durationLabel, isOpen, type Alert } from "./alerts-api";

/** One alert, as a list item: state word + dot, device, description, when, how long. */
export function AlertRow({ alert, nowMs }: { alert: Alert; nowMs: number }) {
  const open = isOpen(alert);
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-sm">
      <span className="flex w-20 shrink-0 items-center gap-1.5">
        <span
          aria-hidden="true"
          className={cn(
            "inline-block size-2 rounded-full",
            open ? "bg-destructive" : "bg-muted-foreground/60",
          )}
        />
        <span className={cn("text-xs font-medium", open ? "text-destructive" : "text-muted-foreground")}>
          {open ? "Ouverte" : "Résolue"}
        </span>
      </span>
      <span className="text-muted-foreground w-28 shrink-0 truncate text-xs">{alert.device_id}</span>
      <span className={cn("flex-1 tabular-nums", !open && "text-muted-foreground")}>
        {describeAlert(alert)}
      </span>
      <span className="text-muted-foreground text-xs tabular-nums">
        à {formatTime(Date.parse(alert.opened_at))} · {durationLabel(alert, nowMs)}
      </span>
    </li>
  );
}
```

```tsx
// frontend/src/features/alerts/alerts-card.tsx
import { Link } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { AlertRow } from "./alert-row";
import { isOpen, type Alert } from "./alerts-api";

export const RESOLVED_SHOWN = 5;

type Props = {
  status: "loading" | "ready" | "error";
  alerts: Alert[];
  /** Injected so tests and the wall screen agree on « depuis 4 min »; defaults to now. */
  nowMs?: number;
  className?: string;
};

/** Wall-screen card: open alerts first, the last few resolved ones, the whole card opens /alertes. */
export function AlertsCard({ status, alerts, nowMs = Date.now(), className }: Props) {
  const open = alerts.filter(isOpen);
  const resolved = alerts.filter((a) => !isOpen(a)).slice(0, RESOLVED_SHOWN);
  return (
    <Link
      to="/alertes"
      aria-label="Alertes, voir l'historique"
      className={cn("block rounded-xl focus-visible:ring-2 focus-visible:outline-none", className)}
    >
      <Card className="hover:bg-accent/40 h-full transition-colors">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium">Alertes</CardTitle>
          {status === "ready" &&
            (open.length > 0 ? (
              <Badge variant="destructive">
                {open.length} {open.length > 1 ? "ouvertes" : "ouverte"}
              </Badge>
            ) : (
              <Badge variant="outline" className="text-muted-foreground">
                Aucune alerte
              </Badge>
            ))}
        </CardHeader>
        <CardContent>
          {status === "loading" && (
            <Skeleton role="status" aria-label="Chargement des alertes" className="h-16 w-full" />
          )}
          {status === "error" && <p className="text-destructive text-sm">Alertes indisponibles</p>}
          {status === "ready" && (open.length > 0 || resolved.length > 0) && (
            <ul className="divide-y">
              {[...open, ...resolved].map((a) => (
                <AlertRow key={a.id} alert={a} nowMs={nowMs} />
              ))}
            </ul>
          )}
          {status === "ready" && open.length === 0 && resolved.length === 0 && (
            <p className="text-muted-foreground text-sm">Aucune alerte enregistrée.</p>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
```

- [ ] **Step 4: Toolchain**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | grep -E "Tests |×"`
Expected: all pass (+3). If `react-refresh/only-export-components` rejects `RESOLVED_SHOWN`, move it to `alerts-api.ts`.

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src/features/alerts && git commit -q -m "$(cat <<'EOF'
feat(frontend): alerts card with open alerts first and the last resolved ones

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: `/alertes` page, route, nav entry with badge

**Files:**
- Create: `frontend/src/features/alerts/alerts-page-content.tsx`, `frontend/src/pages/alerts.tsx`
- Modify: `frontend/src/app/router.tsx`, `frontend/src/app/app-shell.tsx`, `frontend/src/components/app-sidebar.tsx`
- Test: `frontend/src/features/alerts/alerts-page-content.test.tsx`, `frontend/src/components/app-sidebar.test.tsx` (extend)

**Interfaces:**
- Consumes: `useAlerts`, `useAlertCount` (Task 8), `AlertRow` helpers (Task 7), `Device`/`DEVICES_PATH` from `@/features/metrics/metrics-api`, shadcn `Table*`, `ToggleGroup*`, `Select*`, `Label`.
- Produces: `AlertsPageContent()`; `AlertsPage()`; route `/alertes`; nav item « Alertes » with a count badge (`aria-label="N alertes ouvertes"` / « 1 alerte ouverte »), hidden when 0 or unknown.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/alerts/alerts-page-content.test.tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { ALERTS_NOW_MS, makeAlert } from "@/test/alerts";
import { server, VALID_REFRESH } from "@/test/server";
import { AlertsPageContent } from "./alerts-page-content";

function renderPage() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  server.use(
    http.get("/api/alerts", () =>
      HttpResponse.json([
        makeAlert({ id: "open-temp" }),
        makeAlert({
          id: "done-hum",
          device_id: "esp-exterieur",
          metric: "humidity",
          threshold: 70,
          peak_value: 74,
          opened_at: new Date(ALERTS_NOW_MS - 30 * 60_000).toISOString(),
          resolved_at: new Date(ALERTS_NOW_MS - 10 * 60_000).toISOString(),
          resolved_value: 67,
        }),
      ]),
    ),
    http.get("/api/sensors/devices", () =>
      HttpResponse.json([
        { device_id: "esp-interieur", last_seen: "2026-10-06T09:00:00Z" },
        { device_id: "esp-exterieur", last_seen: "2026-10-06T09:00:00Z" },
      ]),
    ),
  );
  return renderRoutes([{ path: "/alertes", element: <AlertsPageContent nowMs={ALERTS_NOW_MS} /> }], "/alertes");
}

describe("AlertsPageContent", () => {
  it("lists every alert in a table, open ones first", async () => {
    renderPage();
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1); // skip the header
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Ouverte");
    expect(rows[0]).toHaveTextContent("Température");
    expect(rows[0]).toHaveTextContent("31,2 °C > 30 °C");
    expect(rows[1]).toHaveTextContent("Résolue");
    expect(rows[1]).toHaveTextContent("20 min");
  });

  it("filters by state and by device", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");
    await user.click(screen.getByRole("radio", { name: "Ouvertes" }));
    expect(screen.getAllByRole("row")).toHaveLength(2);
    await user.click(screen.getByRole("radio", { name: "Toutes" }));
    await user.click(screen.getByRole("combobox", { name: "Appareil" }));
    await user.click(await screen.findByRole("option", { name: "esp-exterieur" }));
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("esp-exterieur");
  });

  it("says so when nothing matches", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");
    await user.click(screen.getByRole("combobox", { name: "Appareil" }));
    await user.click(await screen.findByRole("option", { name: "esp-exterieur" }));
    await user.click(screen.getByRole("radio", { name: "Ouvertes" }));
    expect(screen.getByText("Aucune alerte")).toBeInTheDocument();
  });
});
```

Extend `app-sidebar.test.tsx`: in the links test add `expect(nav.getByRole("link", { name: /^Alertes/ })).toHaveAttribute("href", "/alertes");` and a new test:

```tsx
  it("shows the number of open alerts on the Alertes entry", async () => {
    server.use(http.get("/api/alerts/summary", () => HttpResponse.json({ open: 2 })));
    renderAuthenticated("/");
    const nav = await sidebar();
    expect(await nav.findByLabelText("2 alertes ouvertes")).toBeInTheDocument();
  });
```

(import `http`, `HttpResponse` from `msw` and `server` from `@/test/server` in that file).

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/alerts/alerts-page-content.test.tsx src/components/app-sidebar.test.tsx`
Expected: page test FAILS on the import; sidebar FAILS on the missing « Alertes » link.

- [ ] **Step 3: Page content**

```tsx
// frontend/src/features/alerts/alerts-page-content.tsx
import { useEffect, useState } from "react";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useAuth } from "@/features/auth/use-auth";
import { DEVICES_PATH, type Device } from "@/features/metrics/metrics-api";
import { formatNumber, formatTime } from "@/lib/format-number";
import { cn } from "@/lib/utils";
import {
  DIGITS,
  durationLabel,
  isOpen,
  METRIC_LABELS,
  UNITS,
  type Alert,
} from "./alerts-api";
import { useAlerts } from "./use-alerts";

type StateFilter = "all" | "open" | "resolved";
const ALL_DEVICES = "__all__";

function valueCell(alert: Alert): string {
  if (alert.metric === "gas" && alert.threshold === 0) return "alerte ESP";
  const unit = UNITS[alert.metric];
  const d = DIGITS[alert.metric];
  const sign = alert.direction === "high" ? ">" : "<";
  return `${formatNumber(alert.peak_value, d)} ${unit} ${sign} ${formatNumber(alert.threshold, d)} ${unit}`;
}

/** The /alertes page: filters by state and device, full history in a table. */
export function AlertsPageContent({ nowMs = Date.now() }: { nowMs?: number }) {
  const { authFetch } = useAuth();
  const { status, alerts } = useAlerts();
  const [devices, setDevices] = useState<Device[]>([]);
  const [state, setState] = useState<StateFilter>("all");
  const [device, setDevice] = useState<string>(ALL_DEVICES);

  useEffect(() => {
    let cancelled = false;
    authFetch<Device[]>(DEVICES_PATH)
      .then((list) => {
        if (!cancelled) setDevices(list);
      })
      .catch(() => {
        if (!cancelled) setDevices([]);
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  const rows = alerts
    .filter((a) => state === "all" || (state === "open") === isOpen(a))
    .filter((a) => device === ALL_DEVICES || a.device_id === device);

  return (
    <section aria-labelledby="alerts-title" className="space-y-4">
      <h1 id="alerts-title" className="text-2xl font-semibold">
        Alertes
      </h1>
      <div className="flex flex-wrap items-center gap-4">
        <ToggleGroup
          type="single"
          value={state}
          onValueChange={(v) => v && setState(v as StateFilter)}
          aria-label="État"
          variant="outline"
        >
          <ToggleGroupItem value="all">Toutes</ToggleGroupItem>
          <ToggleGroupItem value="open">Ouvertes</ToggleGroupItem>
          <ToggleGroupItem value="resolved">Résolues</ToggleGroupItem>
        </ToggleGroup>
        <div className="flex items-center gap-2">
          <Label htmlFor="alerts-device">Appareil</Label>
          <Select value={device} onValueChange={setDevice}>
            <SelectTrigger id="alerts-device" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_DEVICES}>Tous</SelectItem>
              {devices.map((d) => (
                <SelectItem key={d.device_id} value={d.device_id}>
                  {d.device_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {status === "loading" && (
        <Skeleton role="status" aria-label="Chargement des alertes" className="h-40 w-full" />
      )}
      {status === "error" && <p className="text-destructive">Alertes indisponibles.</p>}
      {status === "ready" && rows.length === 0 && (
        <p className="text-muted-foreground">Aucune alerte</p>
      )}
      {status === "ready" && rows.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>État</TableHead>
              <TableHead>Appareil</TableHead>
              <TableHead>Métrique</TableHead>
              <TableHead>Valeur / borne</TableHead>
              <TableHead>Ouverte à</TableHead>
              <TableHead>Résolue à</TableHead>
              <TableHead>Durée</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((a) => {
              const open = isOpen(a);
              return (
                <TableRow key={a.id}>
                  <TableCell>
                    <span className={cn("flex items-center gap-1.5 text-xs font-medium", open ? "text-destructive" : "text-muted-foreground")}>
                      <span aria-hidden="true" className={cn("inline-block size-2 rounded-full", open ? "bg-destructive" : "bg-muted-foreground/60")} />
                      {open ? "Ouverte" : "Résolue"}
                    </span>
                  </TableCell>
                  <TableCell>{a.device_id}</TableCell>
                  <TableCell>{METRIC_LABELS[a.metric]}</TableCell>
                  <TableCell className="tabular-nums">{valueCell(a)}</TableCell>
                  <TableCell className="tabular-nums">{formatTime(Date.parse(a.opened_at))}</TableCell>
                  <TableCell className="tabular-nums">
                    {a.resolved_at ? formatTime(Date.parse(a.resolved_at)) : "–"}
                  </TableCell>
                  <TableCell className="tabular-nums">{durationLabel(a, nowMs)}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </section>
  );
}
```

```tsx
// frontend/src/pages/alerts.tsx
import { AlertsPageContent } from "@/features/alerts/alerts-page-content";
import { useDocumentTitle } from "@/lib/use-document-title";

export function AlertsPage() {
  useDocumentTitle("Alertes · sentinel-x");
  return (
    <div className="flex flex-1 flex-col p-6">
      <AlertsPageContent />
    </div>
  );
}
```

Router: import `AlertsPage` and add `{ path: "/alertes", element: <AlertsPage /> }` after `/serveur`. Shell `TITLES`: `"/alertes": "Alertes"`.

- [ ] **Step 4: Nav entry with badge**

In `app-sidebar.tsx`: import `BellRing` from `lucide-react` and `useAlertCount` from `@/features/alerts/use-alert-count`. `NavItemProps` gains `badge?: number | null`. `NAV_ITEMS` gains `{ to: "/alertes", label: "Alertes", icon: BellRing, end: false }` after Serveur. In `AppSidebar`, `const openAlerts = useAlertCount();` and render `<NavItem key={item.to} {...item} badge={item.to === "/alertes" ? openAlerts : null} />`. In `NavItem`, after `<span>{label}</span>` inside the `NavLink`:

```tsx
          {badge ? (
            <span
              aria-label={`${badge} ${badge > 1 ? "alertes ouvertes" : "alerte ouverte"}`}
              className="bg-destructive ml-auto min-w-4 rounded-full px-1 text-center text-[10px] leading-4 font-semibold text-white tabular-nums group-data-[collapsible=icon]:absolute group-data-[collapsible=icon]:-top-0.5 group-data-[collapsible=icon]:-right-0.5 group-data-[collapsible=icon]:ml-0"
            >
              {badge}
            </span>
          ) : null}
```

The `SidebarMenuButton` is `relative` by default in shadcn (`peer/menu-button … relative`); if not, add `className="relative"` to it so the absolute badge anchors to the icon in collapsed mode.

- [ ] **Step 5: Toolchain**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | grep -E "Tests |×"`
Expected: all pass (+4). If Radix `Select` cannot open under jsdom (`hasPointerCapture is not a function`, `scrollIntoView is not a function`), stub them once in `src/test/setup.ts`: `Element.prototype.hasPointerCapture ??= () => false; Element.prototype.setPointerCapture ??= () => {}; Element.prototype.releasePointerCapture ??= () => {}; Element.prototype.scrollIntoView ??= () => {};`. The existing sidebar test that queries `getByRole("link", { name: "Caméra" })` is unaffected; any test matching the « Alertes » link uses `/^Alertes/` because the badge label joins the accessible name.

- [ ] **Step 6: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src && git commit -q -m "$(cat <<'EOF'
feat(frontend): /alertes page with filters and history table, nav entry with open count

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Dashboard integration — alerts card, tiles driven by open alerts

**Files:**
- Modify: `frontend/src/pages/dashboard.tsx`, `frontend/src/features/metrics/metrics-section.tsx`, `frontend/src/features/metrics/metric-tiles.tsx`
- Test: `frontend/src/pages/dashboard.test.tsx` (extend), `frontend/src/features/metrics/metrics-section.test.tsx` (adapt)

**Interfaces:**
- Consumes: `useAlerts` (Task 8), `AlertsCard` (Task 9), `Alert`/`isOpen` (Task 7).
- Produces: `MetricsSection({ openAlerts?: Alert[] })`; `MetricTiles({ latest, previous, openAlerts })`; tile badge « Alerte » when an open alert exists for (device, metric). The « Alerte gaz » tile badge driven by `gas_alert` is removed (the chart marker and the table column keep their reading-based « Alerte gaz »).

- [ ] **Step 1: Write / adapt the failing tests**

In `dashboard.test.tsx` add:

```tsx
  it("shows the alerts card between the top row and the sensors, linking to /alertes", async () => {
    const user = userEvent.setup();
    const { router } = renderDashboard();
    const card = await screen.findByRole("link", { name: "Alertes, voir l'historique" });
    expect(card).toHaveAttribute("href", "/alertes");
    await user.click(card);
    expect(router.state.location.pathname).toBe("/alertes");
  });
```

In `metrics-section.test.tsx`, replace the test "flags a gas alert on the gas tile" by:

```tsx
  it("flags a tile when an open alert exists for its metric", async () => {
    server.use(
      http.get("/api/alerts", () => HttpResponse.json([makeAlert({ metric: "gas", threshold: 0 })])),
    );
    renderDashboard();
    const section = await metrics();
    const gas = within(await section.findByRole("group", { name: "Gaz" }));
    expect(await gas.findByText("Alerte")).toBeInTheDocument();
    expect(within(section.getByRole("group", { name: "Température" })).queryByText("Alerte")).toBeNull();
  });

  it("does not flag a tile from the raw gas flag alone", async () => {
    server.use(
      http.get("/api/sensors/latest", () =>
        HttpResponse.json([makeReading({ gas_level: 1800, gas_alert: true, recorded_at: new Date(NOW_MS).toISOString() })]),
      ),
    );
    renderDashboard();
    const section = await metrics();
    await section.findByRole("group", { name: "Gaz" });
    expect(section.queryByText("Alerte gaz")).not.toBeInTheDocument();
  });
```

(import `makeAlert` from `@/test/alerts`). The first test of that file asserts `queryByText("Alerte gaz")` is absent: keep it.

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/pages/dashboard.test.tsx src/features/metrics/metrics-section.test.tsx`
Expected: the new dashboard test FAILS (no alerts link), "flags a tile when an open alert exists" FAILS (no « Alerte » text).

- [ ] **Step 3: Implement**

`metric-tiles.tsx`: `TileProps.alert?: boolean` stays; the badge text becomes « Alerte » (`<Badge variant="destructive" className="gap-1"><AlertTriangle … />Alerte</Badge>`). `MetricTiles` signature `{ latest, previous, openAlerts }` with `openAlerts: Alert[]` (import type from `@/features/alerts/alerts-api`); compute `const flagged = new Set(openAlerts.map((a) => a.metric));` and pass `alert={flagged.has("temperature")}`, `alert={flagged.has("humidity")}`, `alert={flagged.has("gas")}` (remove `alert={latest?.gas_alert}`).

`metrics-section.tsx`: `export function MetricsSection({ openAlerts = [] }: { openAlerts?: Alert[] })`; `const deviceAlerts = openAlerts.filter((a) => a.device_id === deviceId);` and `<MetricTiles latest={latest} previous={previous} openAlerts={deviceAlerts} />`.

`dashboard.tsx`:

```tsx
import { AlertsCard } from "@/features/alerts/alerts-card";
import { useAlerts } from "@/features/alerts/use-alerts";
…
export function DashboardPage() {
  useDocumentTitle("Dashboard · sentinel-x");
  const alerts = useAlerts();
  return (
    <div className="flex flex-1 flex-col gap-6 p-6">
      <h1 className="sr-only">Dashboard</h1>
      <div className="grid items-stretch gap-4 lg:grid-cols-3">
        <CameraCard className="lg:col-span-2" />
        <ServerHealthCard />
      </div>
      <AlertsCard status={alerts.status} alerts={alerts.alerts} />
      <MetricsSection openAlerts={alerts.open} />
    </div>
  );
}
```

- [ ] **Step 4: Toolchain and build**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | grep -E "Tests |×" && pnpm build 2>&1 | tail -1`
Expected: all pass, build OK.

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src && git commit -q -m "$(cat <<'EOF'
feat(frontend): alerts card on the dashboard, sensor tiles flagged by open alerts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: README, spec status, visual check

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-06-sensor-alerts-design.md` (status line), `backend/.env.example` (if it lists optional settings)

- [ ] **Step 1: README** — insert before `## Front`:

```markdown
## Alertes

Une mesure hors bornes ouvre une alerte (table `alerts`), diffusée sur le WebSocket
(`alert.opened`) ; elle se ferme seule quand la mesure revient dans les bornes avec une marge
(0,5 °C, 2 % d'humidité, 5 % du max gaz) : `alert.resolved`. Bornes, identiques pour tous les
appareils : `ALERT_TEMPERATURE_MIN_C=10`, `ALERT_TEMPERATURE_MAX_C=30`, `ALERT_HUMIDITY_MIN_PCT=20`,
`ALERT_HUMIDITY_MAX_PCT=70`, `ALERT_GAS_MAX_MV` (vide : seul l'état « alerte » de l'ESP compte).
`GET /api/alerts?status=open|resolved|all&device_id=…&limit=…` (ouvertes d'abord),
`GET /api/alerts/summary` → `{"open": n}`. Le Dashboard, la page `/alertes` et le badge de la nav
suivent la liste en direct. Sans matériel : `uv run simulate-sensors --spike
[--spike-metric temperature|humidity|gas]` envoie 5 mesures normales, 6 hors bornes, 5 normales.
```

Spec: `Statut : validé, à implémenter` → `Statut : implémenté le 2026-10-06`. If `backend/.env.example` exists, append the five `ALERT_*` lines commented with their defaults.

- [ ] **Step 2: Visual check** — with the dev stack up (`make dev`), run `cd /Users/namania/git/sentinel-x/backend && uv run alembic upgrade head` is not needed (the api container runs migrations on start; otherwise `docker compose exec api alembic upgrade head`), then `uv run simulate-sensors --spike --base-url http://localhost:8000 --interval 1`. In the browser: the Alertes card shows « 1 ouverte » within a second of the 6th reading, the Température tile carries « Alerte », the nav badge shows 1; after the burst the alert turns « Résolue » and the badge disappears. Open `/alertes`: the row is there with its duration. Check the console for errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add README.md docs backend/.env.example 2>/dev/null; git commit -q -m "$(cat <<'EOF'
docs: sensor alerts, bounds, routes, events and the --spike simulator

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

## Finish

Whole-branch review, then superpowers:finishing-a-development-branch: fast-forward `develop` and `main`, delete the branch, push both. On the Pi, `make deploy` applies migration 0004 at API start.
