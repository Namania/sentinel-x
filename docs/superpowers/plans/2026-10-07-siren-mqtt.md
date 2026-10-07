# Sirène MQTT — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the buzzer state on a retained MQTT topic whenever the set of open alerts changes (gas or high temperature → on), let a user mute it for 15 minutes from the front, and show the siren state live.

**Architecture:** A pure domain decision (`decide`) over the open alerts, the configured triggers and a mute deadline; an application `Siren` service that re-reads open alerts after each alert change, publishes only on change (and at start), broadcasts `siren.state`, and wakes itself when a mute expires; an on-demand aiomqtt publisher; three routes; a `SirenBar` in the front fed by a `useSiren` hook on the shared WebSocket.

**Tech Stack:** Python 3.12, FastAPI, aiomqtt 2.5, pytest; React 19, TypeScript, shadcn (`button`, `badge`), Vitest + MSW 3.

**Spec:** `docs/superpowers/specs/2026-10-07-siren-mqtt-design.md`

## Global Constraints

- Backend: ruff `line-length = 100`, rules `E F I UP B`; `uv run`; integration tests need the compose Postgres.
- MQTT contract verbatim: topic `sentinel/cmd/buzzer`, QoS 1, retained, payload keys `on`, `reason`, `open`, `muted_until`, `at` (dates `…Z`). The topic must stay outside `sentinel/+`.
- Settings verbatim: `mqtt_buzzer_topic = "sentinel/cmd/buzzer"`, `buzzer_triggers = "gas,temperature:high"`, `buzzer_mute_minutes = 15`; an unknown token in `BUZZER_TRIGGERS` refuses to start.
- Without `MQTT_HOST` the siren is computed and shown, nothing is published.
- Frontend: French copy; the siren controls live **outside** the alerts card link; toolchain `pnpm format && pnpm lint && pnpm typecheck && pnpm test && pnpm build` before each commit.
- Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; branch `feat/siren-mqtt` from `main`; linear history; absolute paths in shell commands; `set -o pipefail` in chained commands.

## Review Focus

1. API restart while an alert is open and the broker still holds `on`: the first `refresh` at startup must publish the real state (still `on`, or `off` if the alert resolved meanwhile) — Task 3 tests "publishes at the first refresh even without change", Task 4 wires it in the lifespan.
2. Mute expiry while the API is busy or after a restart: the expiry task must survive the mute being replaced (second mute during a mute) and a restart loses the mute (acceptable: the siren comes back, which errs on the safe side) — Task 3 tests "a second mute replaces the first wake-up".
3. Broker unreachable when publishing: the state must still be served and broadcast, the error logged, and the next change retried — Task 3 test "a failing publisher does not break refresh".
4. `BUZZER_TRIGGERS=""` (empty): the siren never sounds, no crash — Task 1 test.
5. The front's « Couper 15 min » clicked twice quickly: the button is disabled while the request is pending — Task 6 test.

---

## File structure

Backend (new): `domain/siren.py`; `application/alerts/siren.py`; `infrastructure/mqtt/publisher.py`.
Backend (modified): `infrastructure/config.py`, `application/sensors/record.py`, `infrastructure/mqtt/subscriber.py`, `presentation/http/sensors.py`, `presentation/http/alerts.py`, `presentation/dependencies.py`, `presentation/main.py`.
Frontend (new): `features/alerts/siren-api.ts`, `use-siren.ts`, `siren-bar.tsx`; `test/siren.ts`.
Frontend (modified): `test/server.ts`, `pages/dashboard.tsx` (+test), `features/alerts/alerts-page-content.tsx`.

---

## Task 0: Branch

- [ ] `cd /Users/namania/git/sentinel-x && git checkout -q main && git checkout -b feat/siren-mqtt`

---

### Task 1: Domain — triggers and the decision

**Files:**
- Create: `backend/src/app/domain/siren.py`
- Test: `backend/tests/unit/test_siren_domain.py`

**Interfaces:**
- Produces: `Trigger(metric: Metric, direction: Direction | None)`, `parse_triggers(spec: str) -> tuple[Trigger, ...]`, `SirenState(on: bool, reason: Metric | None, open: int, muted_until: datetime | None)`, `decide(open_alerts: Sequence[Alert], triggers: Sequence[Trigger], muted_until: datetime | None, now: datetime) -> SirenState`, `REASON_ORDER`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_siren_domain.py
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.alert import Alert
from app.domain.siren import SirenState, Trigger, decide, parse_triggers

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
DEFAULT = parse_triggers("gas,temperature:high")


def alert(metric="temperature", direction="high") -> Alert:
    return Alert.open(
        device_id="esp-interieur", metric=metric, direction=direction, threshold=30.0, at=NOW, value=31.0
    )


def test_parse_triggers_reads_metric_and_optional_direction():
    assert parse_triggers("gas,temperature:high") == (
        Trigger("gas", None),
        Trigger("temperature", "high"),
    )
    assert parse_triggers(" humidity:low , gas ") == (Trigger("humidity", "low"), Trigger("gas", None))
    assert parse_triggers("") == ()


@pytest.mark.parametrize("spec", ["pressure", "temperature:sideways", "gas:high:now"])
def test_parse_triggers_rejects_unknown_tokens(spec):
    with pytest.raises(ValueError):
        parse_triggers(spec)


def test_no_open_alert_means_silence():
    assert decide([], DEFAULT, None, NOW) == SirenState(on=False, reason=None, open=0, muted_until=None)


def test_only_trigger_metrics_sound():
    humidity = alert("humidity", "high")
    cold = alert("temperature", "low")
    assert decide([humidity, cold], DEFAULT, None, NOW) == SirenState(
        on=False, reason=None, open=2, muted_until=None
    )
    assert decide([alert("temperature", "high")], DEFAULT, None, NOW).on is True


def test_gas_is_the_reason_before_temperature():
    state = decide([alert("temperature", "high"), alert("gas", "high")], DEFAULT, None, NOW)
    assert (state.on, state.reason, state.open) == (True, "gas", 2)


def test_an_active_mute_silences_but_keeps_the_reason():
    until = NOW + timedelta(minutes=10)
    state = decide([alert("gas", "high")], DEFAULT, until, NOW)
    assert state == SirenState(on=False, reason="gas", open=1, muted_until=until)


def test_an_expired_mute_is_forgotten():
    state = decide([alert("gas", "high")], DEFAULT, NOW - timedelta(seconds=1), NOW)
    assert state == SirenState(on=True, reason="gas", open=1, muted_until=None)


def test_empty_triggers_never_sound():
    assert decide([alert("gas", "high")], (), None, NOW).on is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_siren_domain.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.siren'`.

- [ ] **Step 3: Implement**

```python
# backend/src/app/domain/siren.py
"""The siren: should the buzzer sound, given the open alerts, the triggers and a mute?"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from app.domain.alert import METRICS, Alert, Direction, Metric

REASON_ORDER: tuple[Metric, ...] = ("gas", "temperature", "humidity")
DIRECTIONS = ("low", "high")


@dataclass(frozen=True, slots=True)
class Trigger:
    metric: Metric
    direction: Direction | None  # None → both directions

    def matches(self, alert: Alert) -> bool:
        return alert.metric == self.metric and self.direction in (None, alert.direction)


def parse_triggers(spec: str) -> tuple[Trigger, ...]:
    """`"gas,temperature:high"` → triggers; an unknown metric or direction is a ValueError."""
    triggers: list[Trigger] = []
    for raw in spec.split(","):
        token = raw.strip()
        if not token:
            continue
        metric, _, direction = token.partition(":")
        if metric not in METRICS:
            raise ValueError(f"unknown metric in BUZZER_TRIGGERS: {token!r}")
        if direction and (direction not in DIRECTIONS or ":" in direction):
            raise ValueError(f"unknown direction in BUZZER_TRIGGERS: {token!r}")
        triggers.append(
            Trigger(cast(Metric, metric), cast(Direction, direction) if direction else None)
        )
    return tuple(triggers)


@dataclass(frozen=True, slots=True)
class SirenState:
    on: bool
    reason: Metric | None
    open: int
    muted_until: datetime | None


def decide(
    open_alerts: Sequence[Alert],
    triggers: Sequence[Trigger],
    muted_until: datetime | None,
    now: datetime,
) -> SirenState:
    matching = [a for a in open_alerts if any(t.matches(a) for t in triggers)]
    reason = min((a.metric for a in matching), key=REASON_ORDER.index, default=None)
    mute_active = muted_until is not None and muted_until > now
    return SirenState(
        on=bool(matching) and not mute_active,
        reason=reason,
        open=len(open_alerts),
        muted_until=muted_until if mute_active else None,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_siren_domain.py -q && uv run ruff check . && uv run ruff format --check .`
Expected: `10 passed`, ruff clean (run `uv run ruff format .` if needed).

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend/src/app/domain/siren.py backend/tests/unit/test_siren_domain.py && git commit -q -m "$(cat <<'EOF'
feat(siren): domain triggers and the buzzer decision

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Settings

**Files:**
- Modify: `backend/src/app/infrastructure/config.py`
- Test: `backend/tests/unit/test_settings.py` (append)

**Interfaces:**
- Consumes: `parse_triggers` (Task 1).
- Produces: `mqtt_buzzer_topic: str`, `buzzer_triggers: str`, `buzzer_mute_minutes: int`, `Settings.triggers() -> tuple[Trigger, ...]`; invalid triggers → `ValidationError`.

- [ ] **Step 1: Write the failing tests**

```python
def test_siren_defaults_and_trigger_accessor():
    from app.domain.siren import Trigger

    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.mqtt_buzzer_topic == "sentinel/cmd/buzzer"
    assert settings.buzzer_mute_minutes == 15
    assert settings.triggers() == (Trigger("gas", None), Trigger("temperature", "high"))


def test_unknown_buzzer_trigger_is_refused(monkeypatch):
    monkeypatch.setenv("BUZZER_TRIGGERS", "gas,pressure")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="x" * 32)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_settings.py -q`
Expected: 2 FAIL (`AttributeError: ... 'mqtt_buzzer_topic'`, no ValidationError).

- [ ] **Step 3: Implement**

In `config.py`, import `from app.domain.siren import Trigger, parse_triggers`; after the alert bounds block:

```python
    # Siren: the ESP32 buzzer follows a retained MQTT state message (see docs/.../siren spec).
    mqtt_buzzer_topic: str = "sentinel/cmd/buzzer"
    buzzer_triggers: str = "gas,temperature:high"  # "metric" or "metric:low|high", comma-separated
    buzzer_mute_minutes: int = 15

    def triggers(self) -> tuple[Trigger, ...]:
        return parse_triggers(self.buzzer_triggers)
```

and extend the existing `@model_validator(mode="after")` method to also call `self.triggers()` (a `ValueError` becomes a `ValidationError`). Add `ge=1, le=240` on `buzzer_mute_minutes` via `Field`.

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_settings.py -q && uv run ruff check .`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend/src/app/infrastructure/config.py backend/tests/unit/test_settings.py && git commit -q -m "$(cat <<'EOF'
feat(siren): buzzer topic, triggers and mute duration in settings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `Siren` service and the `RecordReading` hook

**Files:**
- Create: `backend/src/app/application/alerts/siren.py`
- Modify: `backend/src/app/application/sensors/record.py`
- Test: `backend/tests/unit/test_siren.py`, `backend/tests/unit/test_record_reading.py` (append)

**Interfaces:**
- Consumes: `decide`, `SirenState`, `Trigger` (Task 1); `UnitOfWork.alerts.list("open", None, 500)`; `EventBroadcaster`.
- Produces: `SirenPublisher` protocol (`async publish(state, at)`); `siren_to_dict(state, at) -> dict`; `Siren(uow_factory, publisher, broadcaster, triggers, mute_minutes, clock=_utc_now, sleep=asyncio.sleep)` with `state`, `async refresh()`, `async mute(by: UUID)`, `async unmute(by: UUID)`, `close()`; `RecordReading(..., on_alerts_changed: Callable[[], Awaitable[None]] | None = None)`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_siren.py
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.application.alerts.siren import Siren, siren_to_dict
from app.domain.alert import Alert
from app.domain.siren import SirenState, parse_triggers
from tests.unit.fakes import InMemoryUnitOfWork

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
TRIGGERS = parse_triggers("gas,temperature:high")


class RecordingPublisher:
    def __init__(self, fail=False) -> None:
        self.published: list[tuple[SirenState, datetime]] = []
        self.fail = fail

    async def publish(self, state, at):
        if self.fail:
            raise ConnectionError("broker down")
        self.published.append((state, at))


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.events = []

    async def broadcast(self, event):
        self.events.append(event)

    async def send_to_user(self, user_id, event):
        self.events.append(event)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def gas_alert() -> Alert:
    return Alert.open(device_id="esp-interieur", metric="gas", direction="high", threshold=0.0, at=NOW, value=1800.0)


def build(fail=False):
    uow = InMemoryUnitOfWork()
    publisher = RecordingPublisher(fail)
    bus = RecordingBroadcaster()
    clock = Clock()
    sleeps: list[float] = []
    wake = asyncio.Event()

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await wake.wait()

    siren = Siren(lambda: uow, publisher, bus, TRIGGERS, mute_minutes=15, clock=clock, sleep=sleep)
    return siren, uow, publisher, bus, clock, sleeps, wake


async def test_the_first_refresh_publishes_even_when_silent():
    siren, _, publisher, bus, _, _, _ = build()
    state = await siren.refresh()
    assert state == SirenState(on=False, reason=None, open=0, muted_until=None)
    assert [s.on for s, _ in publisher.published] == [False]
    assert bus.events[0]["type"] == "siren.state"
    assert bus.events[0]["data"] == siren_to_dict(state, NOW)
    assert bus.events[0]["data"]["at"] == "2026-10-07T09:00:00Z"


async def test_refresh_publishes_only_on_change():
    siren, uow, publisher, _, _, _, _ = build()
    await siren.refresh()
    await siren.refresh()
    assert len(publisher.published) == 1
    await uow.alerts.add(gas_alert())
    state = await siren.refresh()
    assert (state.on, state.reason) == (True, "gas")
    assert len(publisher.published) == 2
    await siren.refresh()
    assert len(publisher.published) == 2


async def test_mute_silences_and_schedules_the_wake_up():
    siren, uow, publisher, _, clock, sleeps, wake = build()
    await uow.alerts.add(gas_alert())
    await siren.refresh()
    state = await siren.mute(by=uuid4())
    assert state.on is False
    assert state.muted_until == NOW + timedelta(minutes=15)
    assert publisher.published[-1][0].on is False
    assert sleeps == [15 * 60]
    # The mute expires: the siren comes back on its own because the alert is still open.
    clock.now = NOW + timedelta(minutes=15, seconds=1)
    wake.set()
    await asyncio.sleep(0.01)
    assert publisher.published[-1][0].on is True
    assert siren.state.muted_until is None


async def test_a_second_mute_replaces_the_first_wake_up():
    siren, uow, publisher, _, clock, sleeps, _ = build()
    await uow.alerts.add(gas_alert())
    await siren.refresh()
    await siren.mute(by=uuid4())
    clock.now = NOW + timedelta(minutes=5)
    state = await siren.mute(by=uuid4())
    assert state.muted_until == NOW + timedelta(minutes=20)
    assert sleeps == [15 * 60, 15 * 60]
    siren.close()


async def test_unmute_restores_the_siren():
    siren, uow, publisher, _, _, _, _ = build()
    await uow.alerts.add(gas_alert())
    await siren.refresh()
    await siren.mute(by=uuid4())
    state = await siren.unmute(by=uuid4())
    assert (state.on, state.muted_until) == (True, None)
    assert publisher.published[-1][0].on is True
    siren.close()


async def test_a_failing_publisher_does_not_break_refresh(caplog):
    siren, uow, publisher, bus, _, _, _ = build(fail=True)
    await uow.alerts.add(gas_alert())
    state = await siren.refresh()
    assert state.on is True
    assert bus.events[-1]["type"] == "siren.state"
    assert "broker down" in caplog.text
```

Append to `backend/tests/unit/test_record_reading.py`:

```python
async def test_on_alerts_changed_fires_only_when_an_alert_opens_or_closes():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    calls = 0

    async def changed() -> None:
        nonlocal calls
        calls += 1

    use_case = RecordReading(uow, bus, clock=lambda: NOW, on_alerts_changed=changed)
    await use_case.execute(make_input())  # in range: nothing
    assert calls == 0
    await use_case.execute(make_input(temperature_c=30.4))  # opens
    assert calls == 1
    await use_case.execute(make_input(temperature_c=31.0))  # worsens: no event
    assert calls == 1
    await use_case.execute(make_input(temperature_c=29.0))  # resolves
    assert calls == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_siren.py tests/unit/test_record_reading.py -q`
Expected: FAIL (`ModuleNotFoundError: app.application.alerts.siren`; `TypeError: unexpected keyword argument 'on_alerts_changed'`).

- [ ] **Step 3: Implement the service**

```python
# backend/src/app/application/alerts/siren.py
"""The siren service: recompute the buzzer state after alert changes, publish it, mute it."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.siren import SirenState, Trigger, decide

logger = logging.getLogger(__name__)

EVENT_TYPE = "siren.state"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_z(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def siren_to_dict(state: SirenState, at: datetime) -> dict[str, Any]:
    """The MQTT payload and the WebSocket event body: `on` first, dates as `…Z`."""
    data = asdict(state)
    data["muted_until"] = _iso_z(state.muted_until)
    data["at"] = _iso_z(at)
    return data


class SirenPublisher(Protocol):
    async def publish(self, state: SirenState, at: datetime) -> None: ...


class Siren:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        publisher: SirenPublisher | None,
        broadcaster: EventBroadcaster,
        triggers: Sequence[Trigger],
        mute_minutes: int,
        clock: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._broadcaster = broadcaster
        self._triggers = tuple(triggers)
        self._mute = timedelta(minutes=mute_minutes)
        self._clock = clock
        self._sleep = sleep
        self._state = SirenState(on=False, reason=None, open=0, muted_until=None)
        self._muted_until: datetime | None = None
        self._announced = False
        self._wake_up: asyncio.Task[None] | None = None

    @property
    def state(self) -> SirenState:
        return self._state

    async def refresh(self) -> SirenState:
        """Re-read the open alerts, publish and broadcast if the state changed (or at start)."""
        now = self._clock()
        async with self._uow_factory() as uow:
            open_alerts = await uow.alerts.list("open", None, 500)
        new = decide(open_alerts, self._triggers, self._muted_until, now)
        changed = (
            not self._announced
            or new.on != self._state.on
            or new.reason != self._state.reason
            or new.muted_until != self._state.muted_until
        )
        self._state = new
        if changed:
            await self._announce(new, now)
        return new

    async def mute(self, by: UUID) -> SirenState:
        self._muted_until = self._clock() + self._mute
        logger.info("siren muted until %s by %s", self._muted_until.isoformat(), by)
        self._schedule_wake_up(self._mute.total_seconds())
        return await self.refresh()

    async def unmute(self, by: UUID) -> SirenState:
        self._muted_until = None
        logger.info("siren unmuted by %s", by)
        self._cancel_wake_up()
        return await self.refresh()

    def close(self) -> None:
        self._cancel_wake_up()

    async def _announce(self, state: SirenState, at: datetime) -> None:
        self._announced = True
        if self._publisher is not None:
            try:
                await self._publisher.publish(state, at)
            except Exception:  # noqa: BLE001 - the state is still served; the next change retries
                logger.exception("siren: publishing the buzzer state failed")
        await self._broadcaster.broadcast({"type": EVENT_TYPE, "data": siren_to_dict(state, at)})

    def _schedule_wake_up(self, seconds: float) -> None:
        self._cancel_wake_up()

        async def wake_up() -> None:
            await self._sleep(seconds)
            await self.refresh()  # the mute has expired: the siren comes back if needed

        self._wake_up = asyncio.create_task(wake_up(), name="siren-wake-up")

    def _cancel_wake_up(self) -> None:
        if self._wake_up is not None:
            self._wake_up.cancel()
            self._wake_up = None
```

`asdict(state)` keeps the field order `on, reason, open, muted_until`, so `on` is the first key.

- [ ] **Step 4: The hook in `RecordReading`**

In `record.py`: import `Awaitable` from `collections.abc`; constructor param `on_alerts_changed: Callable[[], Awaitable[None]] | None = None` (after `clock`), stored as `self._on_alerts_changed`. At the end of `execute`, after the alert events loop and before `return output`:

```python
        if alert_events and self._on_alerts_changed is not None:
            await self._on_alerts_changed()
```

- [ ] **Step 5: Run and commit**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run ruff check --fix . >/dev/null; uv run ruff format . >/dev/null; uv run ruff check . && uv run pytest tests/unit -q 2>&1 | tail -1`
Expected: all unit tests pass.

```bash
cd /Users/namania/git/sentinel-x && git add backend && git commit -q -m "$(cat <<'EOF'
feat(siren): Siren service publishes the buzzer state on change, mutes for a while, wakes itself

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: MQTT publisher, routes, wiring

**Files:**
- Create: `backend/src/app/infrastructure/mqtt/publisher.py`
- Modify: `backend/src/app/presentation/http/alerts.py`, `backend/src/app/presentation/dependencies.py`, `backend/src/app/presentation/main.py`, `backend/src/app/infrastructure/mqtt/subscriber.py`, `backend/src/app/presentation/http/sensors.py`
- Test: `backend/tests/unit/test_mqtt_publisher.py`, `backend/tests/integration/test_siren_http.py`

**Interfaces:**
- Consumes: `Siren`, `siren_to_dict` (Task 3); `connect_factory(host, port, identifier)` from `infrastructure/mqtt/client.py`.
- Produces: `MqttSirenPublisher(connect, topic)`; `app.state.siren`; `SirenDep`; routes `GET /alerts/siren`, `POST /alerts/siren/mute`, `DELETE /alerts/siren/mute` → `SirenResponse(on, reason, open, muted_until)`; `MqttSubscriber(..., on_alerts_changed=None)`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_mqtt_publisher.py
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from app.domain.siren import SirenState
from app.infrastructure.mqtt.publisher import MqttSirenPublisher


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def publish(self, topic, payload, qos=0, retain=False):
        self.calls.append({"topic": topic, "payload": payload, "qos": qos, "retain": retain})


async def test_publishes_the_retained_state_on_the_topic():
    client = FakeClient()
    opened = 0

    @asynccontextmanager
    async def connect():
        nonlocal opened
        opened += 1
        yield client

    publisher = MqttSirenPublisher(connect, "sentinel/cmd/buzzer")
    at = datetime(2026, 10, 7, 9, 12, 3, tzinfo=UTC)
    await publisher.publish(SirenState(on=True, reason="gas", open=2, muted_until=None), at)
    assert opened == 1
    call = client.calls[0]
    assert (call["topic"], call["qos"], call["retain"]) == ("sentinel/cmd/buzzer", 1, True)
    body = json.loads(call["payload"])
    assert list(body)[0] == "on"
    assert body == {"on": True, "reason": "gas", "open": 2, "muted_until": None, "at": "2026-10-07T09:12:03Z"}
```

```python
# backend/tests/integration/test_siren_http.py
from tests.integration.conftest import DEVICE_HEADERS, create_user_and_login

GAS_ALERT = {"device_id": "esp-interieur", "gaz": {"mostGaz": True, "quantity": 1800}}
GAS_OK = {"device_id": "esp-interieur", "gaz": {"mostGaz": False, "quantity": 400}}
HUMID = {"device_id": "esp-interieur", "temperature": {"humidity": 75.0, "temp": 22.0}}


def auth(client):
    return {"Authorization": f"Bearer {create_user_and_login(client)['access_token']}"}


def test_siren_routes_require_a_token(client):
    assert client.get("/alerts/siren").status_code == 401
    assert client.post("/alerts/siren/mute").status_code == 401
    assert client.delete("/alerts/siren/mute").status_code == 401


def test_siren_follows_gas_alerts_and_the_mute(client):
    headers = auth(client)
    assert client.get("/alerts/siren", headers=headers).json() == {
        "on": False, "reason": None, "open": 0, "muted_until": None,
    }
    client.post("/sensors/readings", json=HUMID, headers=DEVICE_HEADERS)  # humidity: no siren
    assert client.get("/alerts/siren", headers=headers).json()["on"] is False

    client.post("/sensors/readings", json=GAS_ALERT, headers=DEVICE_HEADERS)
    state = client.get("/alerts/siren", headers=headers).json()
    assert (state["on"], state["reason"], state["open"]) == (True, "gas", 2)

    muted = client.post("/alerts/siren/mute", headers=headers).json()
    assert muted["on"] is False and muted["muted_until"] is not None
    assert client.delete("/alerts/siren/mute", headers=headers).json()["on"] is True

    client.post("/sensors/readings", json=GAS_OK, headers=DEVICE_HEADERS)
    assert client.get("/alerts/siren", headers=headers).json()["on"] is False


def test_siren_events_follow_alert_events_on_the_websocket(client):
    tokens = create_user_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        client.post("/sensors/readings", json=GAS_ALERT, headers=DEVICE_HEADERS)
        assert [ws.receive_json()["type"] for _ in range(3)] == ["sensor.reading", "alert.opened", "siren.state"]
        client.post("/alerts/siren/mute", headers=headers)
        event = ws.receive_json()
        assert event["type"] == "siren.state" and event["data"]["on"] is False
        client.delete("/alerts/siren/mute", headers=headers)
        assert ws.receive_json()["data"]["on"] is True
```

The siren's state lives in `app.state` across tests while the schema is reset per test: `GET /alerts/siren` therefore **refreshes** from the database before answering (cheap, one query), which also makes it self-healing in production.

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_mqtt_publisher.py tests/integration/test_siren_http.py -q`
Expected: FAIL (missing module; 404s).

- [ ] **Step 3: Publisher**

```python
# backend/src/app/infrastructure/mqtt/publisher.py
"""Publish the siren state as a retained MQTT message, opening a connection on demand."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from app.application.alerts.siren import siren_to_dict
from app.domain.siren import SirenState


class PublishingClient(Protocol):
    async def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> object: ...


Connect = Callable[[], AbstractAsyncContextManager[PublishingClient]]


class MqttSirenPublisher:
    """One short connection per publication: state changes are rare, nothing to keep alive."""

    def __init__(self, connect: Connect, topic: str) -> None:
        self._connect = connect
        self._topic = topic

    async def publish(self, state: SirenState, at: datetime) -> None:
        payload = json.dumps(siren_to_dict(state, at))
        async with self._connect() as client:
            await client.publish(self._topic, payload, qos=1, retain=True)
```

- [ ] **Step 4: Routes and wiring**

`dependencies.py`: `from app.application.alerts.siren import Siren`; `def get_siren(conn) -> Siren: return conn.app.state.siren`; `SirenDep = Annotated[Siren, Depends(get_siren)]`.

`alerts.py` (imports `SirenDep`, `SirenState`, `Metric`):

```python
class SirenResponse(BaseModel):
    on: bool
    reason: Metric | None
    open: int
    muted_until: datetime | None

    @classmethod
    def from_state(cls, state: SirenState) -> "SirenResponse":
        return cls(on=state.on, reason=state.reason, open=state.open, muted_until=state.muted_until)


@router.get("/siren", response_model=SirenResponse, summary="État de la sirène (buzzer de l'ESP32)")
async def siren_state(_: CurrentUserIdDep, siren: SirenDep) -> SirenResponse:
    return SirenResponse.from_state(await siren.refresh())


@router.post("/siren/mute", response_model=SirenResponse, summary="Couper la sirène quelques minutes")
async def mute_siren(user_id: CurrentUserIdDep, siren: SirenDep) -> SirenResponse:
    return SirenResponse.from_state(await siren.mute(by=user_id))


@router.delete("/siren/mute", response_model=SirenResponse, summary="Réactiver la sirène")
async def unmute_siren(user_id: CurrentUserIdDep, siren: SirenDep) -> SirenResponse:
    return SirenResponse.from_state(await siren.unmute(by=user_id))
```

`subscriber.py`: constructor param `on_alerts_changed: Callable[[], Awaitable[None]] | None = None`, passed to `RecordReading(..., on_alerts_changed=self._on_alerts_changed)`.

`sensors.py` `post_reading`: add `siren: SirenDep` and pass `on_alerts_changed=siren.refresh`.

`main.py`:
- after `app.state.hub = ConnectionHub()`:

```python
    app.state.siren = Siren(
        uow_factory=lambda: SqlAlchemyUnitOfWork(app.state.session_factory),
        publisher=_build_siren_publisher(settings),
        broadcaster=app.state.hub,
        triggers=settings.triggers(),
        mute_minutes=settings.buzzer_mute_minutes,
    )
```

(`app.state.session_factory` must be assigned before; it already is on the line above `hub` — keep the order `session_factory`, `hub`, `siren`.)

- `_build_siren_publisher(settings) -> MqttSirenPublisher | None`: `None` without `mqtt_host`, else `MqttSirenPublisher(connect_factory(settings.mqtt_host, settings.mqtt_port, identifier="sentinel-x-siren"), settings.mqtt_buzzer_topic)`.
- `_start_mqtt_subscriber`: pass `on_alerts_changed=app.state.siren.refresh`.
- lifespan: right after the tasks list is built, `await _announce_siren(app)` where:

```python
async def _announce_siren(app: FastAPI) -> None:
    """Publish the real state at start: the broker may still hold yesterday's retained `on`."""
    try:
        await app.state.siren.refresh()
    except Exception:  # noqa: BLE001 - the database may not be ready; the first alert will refresh
        logger.warning("siren: initial state not published", exc_info=True)
```

(`logger = logging.getLogger(__name__)` at module level.) In `finally`, call `app.state.siren.close()` before awaiting the tasks.

- [ ] **Step 5: Run the whole backend suite and commit**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run ruff check --fix . >/dev/null; uv run ruff format . >/dev/null; uv run ruff check . && uv run pytest -q 2>&1 | tail -1`
Expected: all pass (previous 220 + 10 + 2 + 7 + 1 + 1 + 3 = 244).

```bash
cd /Users/namania/git/sentinel-x && git add backend && git commit -q -m "$(cat <<'EOF'
feat(siren): retained MQTT state on sentinel/cmd/buzzer, mute routes, startup announcement

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Front — `siren-api.ts`, `useSiren`, fixtures

**Files:**
- Create: `frontend/src/features/alerts/siren-api.ts`, `frontend/src/features/alerts/use-siren.ts`, `frontend/src/test/siren.ts`
- Modify: `frontend/src/test/server.ts`
- Test: `frontend/src/features/alerts/siren-api.test.ts`, `frontend/src/features/alerts/use-siren.test.tsx`

**Interfaces:**
- Produces: `SirenState = { on: boolean; reason: Metric | null; open: number; muted_until: string | null }`; `SIREN_PATH = "/alerts/siren"`, `SIREN_MUTE_PATH = "/alerts/siren/mute"`; `sirenLabel(state): string`; `useSiren(): { status, state, connected, pending, mute(), unmute() }`. Fixtures `makeSiren(overrides)`; MSW handlers `GET /api/alerts/siren` (quiet), `POST`/`DELETE /api/alerts/siren/mute`.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/features/alerts/siren-api.test.ts
import { describe, expect, it } from "vitest";
import { makeSiren } from "@/test/siren";
import { sirenLabel } from "./siren-api";

describe("sirenLabel", () => {
  it("names the three states", () => {
    expect(sirenLabel(makeSiren())).toBe("Sirène au repos");
    expect(sirenLabel(makeSiren({ on: true, reason: "gas", open: 1 }))).toBe("Sirène active : gaz");
    expect(sirenLabel(makeSiren({ on: true, reason: "temperature", open: 1 }))).toBe(
      "Sirène active : température",
    );
    expect(
      sirenLabel(makeSiren({ reason: "gas", open: 1, muted_until: "2026-10-07T07:27:00Z" })),
    ).toBe("Sirène coupée jusqu'à 09:27");
  });
});
```

```tsx
// frontend/src/features/alerts/use-siren.test.tsx
import { act, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import { makeSiren } from "@/test/siren";
import { useSiren } from "./use-siren";

function Probe() {
  const { status, state, mute, unmute } = useSiren();
  return (
    <div>
      <p>status:{status}</p>
      <p>on:{String(state?.on)}</p>
      <p>muted:{state?.muted_until ?? "-"}</p>
      <button onClick={() => void mute()}>mute</button>
      <button onClick={() => void unmute()}>unmute</button>
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

describe("useSiren", () => {
  it("loads the state and follows siren.state events", async () => {
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(JSON.stringify({ type: "siren.state", data: makeSiren({ on: true, reason: "gas", open: 1 }) }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(await screen.findByText("on:true")).toBeInTheDocument();
  });

  it("mutes and unmutes through the API and shows the response at once", async () => {
    const calls: string[] = [];
    server.use(
      http.post("/api/alerts/siren/mute", () => {
        calls.push("post");
        return HttpResponse.json(makeSiren({ reason: "gas", open: 1, muted_until: "2026-10-07T07:27:00Z" }));
      }),
      http.delete("/api/alerts/siren/mute", () => {
        calls.push("delete");
        return HttpResponse.json(makeSiren({ on: true, reason: "gas", open: 1 }));
      }),
    );
    renderProbe();
    await screen.findByText("status:ready");
    await act(async () => screen.getByText("mute").click());
    expect(await screen.findByText("muted:2026-10-07T07:27:00Z")).toBeInTheDocument();
    await act(async () => screen.getByText("unmute").click());
    expect(await screen.findByText("on:true")).toBeInTheDocument();
    expect(calls).toEqual(["post", "delete"]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/alerts/siren-api.test.ts src/features/alerts/use-siren.test.tsx`
Expected: FAIL on the missing imports.

- [ ] **Step 3: Implement**

```ts
// frontend/src/features/alerts/siren-api.ts
import { formatTime } from "@/lib/format-number";
import type { Metric } from "./alerts-api";

export type SirenState = {
  on: boolean;
  reason: Metric | null;
  open: number;
  muted_until: string | null;
};

export const SIREN_PATH = "/alerts/siren";
export const SIREN_MUTE_PATH = "/alerts/siren/mute";

const REASONS: Record<Metric, string> = { gas: "gaz", temperature: "température", humidity: "humidité" };

/** « Sirène active : gaz », « Sirène coupée jusqu'à 09:27 », « Sirène au repos ». */
export function sirenLabel(state: SirenState): string {
  if (state.muted_until) return `Sirène coupée jusqu'à ${formatTime(Date.parse(state.muted_until))}`;
  if (state.on && state.reason) return `Sirène active : ${REASONS[state.reason]}`;
  return "Sirène au repos";
}
```

```ts
// frontend/src/features/alerts/use-siren.ts
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { useEventStream } from "@/features/realtime/use-event-stream";
import { useResyncKey } from "@/features/realtime/use-resync-key";
import { SIREN_MUTE_PATH, SIREN_PATH, type SirenState } from "./siren-api";

type Status = "loading" | "ready" | "error";

/** The siren state, live, with the two actions. Events are authoritative; a response is shown at once. */
export function useSiren() {
  const { authFetch } = useAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [state, setState] = useState<SirenState | null>(null);
  const [pending, setPending] = useState(false);
  const loaded = useRef(false);

  const onEvent = useCallback((type: string, data: unknown) => {
    if (type !== "siren.state" || !data) return;
    loaded.current = true;
    setState(data as SirenState);
    setStatus("ready");
  }, []);
  const { connected } = useEventStream(true, onEvent);
  const resyncKey = useResyncKey(connected);

  useEffect(() => {
    let cancelled = false;
    authFetch<SirenState>(SIREN_PATH)
      .then((fresh) => {
        if (cancelled) return;
        loaded.current = true;
        setState(fresh);
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled && !loaded.current) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, resyncKey]);

  const call = useCallback(
    async (method: "POST" | "DELETE") => {
      setPending(true);
      try {
        const fresh = await authFetch<SirenState>(SIREN_MUTE_PATH, { method });
        setState(fresh);
        setStatus("ready");
      } catch {
        // The bar keeps the previous state; the next event will say what happened.
      } finally {
        setPending(false);
      }
    },
    [authFetch],
  );
  const mute = useCallback(() => call("POST"), [call]);
  const unmute = useCallback(() => call("DELETE"), [call]);

  return { status, state, connected, pending, mute, unmute };
}
```

```ts
// frontend/src/test/siren.ts
import type { SirenState } from "@/features/alerts/siren-api";

export function makeSiren(overrides: Partial<SirenState> = {}): SirenState {
  return { on: false, reason: null, open: 0, muted_until: null, ...overrides };
}
```

`test/server.ts`: import `makeSiren` and add handlers `GET /api/alerts/siren` → `makeSiren()`, `POST /api/alerts/siren/mute` → `makeSiren({ muted_until: "2026-10-07T07:15:00Z" })`, `DELETE /api/alerts/siren/mute` → `makeSiren()`, all behind `isValidAccessToken`.

- [ ] **Step 4: Toolchain and commit**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | grep -E "Tests |×"`
Expected: all pass (+3).

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src && git commit -q -m "$(cat <<'EOF'
feat(frontend): siren state hook and labels

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `SirenBar` on the Dashboard and `/alertes`

**Files:**
- Create: `frontend/src/features/alerts/siren-bar.tsx`
- Modify: `frontend/src/pages/dashboard.tsx`, `frontend/src/features/alerts/alerts-page-content.tsx`
- Test: `frontend/src/features/alerts/siren-bar.test.tsx`, `frontend/src/pages/dashboard.test.tsx` (extend)

**Interfaces:**
- Consumes: `useSiren` (Task 5), `sirenLabel`; shadcn `Button`.
- Produces: `SirenBar({ className? })` — `role="status"` region named « Sirène », a `Button` « Couper 15 min » when `on`, « Réactiver » when muted, none at rest; the button is disabled while `pending`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/alerts/siren-bar.test.tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderWithProviders } from "@/test/render";
import { server, VALID_REFRESH } from "@/test/server";
import { makeSiren } from "@/test/siren";
import { SirenBar } from "./siren-bar";

function renderBar() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderWithProviders(<SirenBar />);
}

describe("SirenBar", () => {
  it("rests quietly with no button when nothing sounds", async () => {
    renderBar();
    const bar = within(await screen.findByRole("status", { name: "Sirène" }));
    expect(await bar.findByText("Sirène au repos")).toBeInTheDocument();
    expect(bar.queryByRole("button")).toBeNull();
  });

  it("offers to mute while sounding and shows the mute at once", async () => {
    const user = userEvent.setup();
    let resolvePost: (() => void) | null = null;
    server.use(
      http.get("/api/alerts/siren", () => HttpResponse.json(makeSiren({ on: true, reason: "gas", open: 1 }))),
      http.post("/api/alerts/siren/mute", async () => {
        await new Promise<void>((r) => (resolvePost = r));
        return HttpResponse.json(makeSiren({ reason: "gas", open: 1, muted_until: "2026-10-07T07:27:00Z" }));
      }),
    );
    renderBar();
    const bar = within(await screen.findByRole("status", { name: "Sirène" }));
    expect(await bar.findByText("Sirène active : gaz")).toBeInTheDocument();
    const button = bar.getByRole("button", { name: "Couper 15 min" });
    await user.click(button);
    expect(button).toBeDisabled(); // a second click while the request is pending does nothing
    resolvePost!();
    expect(await bar.findByText("Sirène coupée jusqu'à 09:27")).toBeInTheDocument();
    expect(bar.getByRole("button", { name: "Réactiver" })).toBeInTheDocument();
  });

  it("re-arms the siren", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/alerts/siren", () =>
        HttpResponse.json(makeSiren({ reason: "gas", open: 1, muted_until: "2026-10-07T07:27:00Z" })),
      ),
      http.delete("/api/alerts/siren/mute", () => HttpResponse.json(makeSiren({ on: true, reason: "gas", open: 1 }))),
    );
    renderBar();
    const bar = within(await screen.findByRole("status", { name: "Sirène" }));
    await user.click(await bar.findByRole("button", { name: "Réactiver" }));
    await waitFor(() => expect(bar.getByText("Sirène active : gaz")).toBeInTheDocument());
  });
});
```

Extend `dashboard.test.tsx` with:

```tsx
  it("shows the siren bar outside the alerts card link", async () => {
    renderDashboard();
    const bar = await screen.findByRole("status", { name: "Sirène" });
    expect(bar.closest("a")).toBeNull();
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/alerts/siren-bar.test.tsx src/pages/dashboard.test.tsx`
Expected: FAIL (missing import; no « Sirène » status).

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/alerts/siren-bar.tsx
import { Bell, BellOff, BellRing } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { sirenLabel } from "./siren-api";
import { useSiren } from "./use-siren";

/** The ESP32 buzzer, as the API drives it: what it does now, and the button to mute or re-arm it. */
export function SirenBar({ className }: { className?: string }) {
  const { status, state, pending, mute, unmute } = useSiren();
  const muted = Boolean(state?.muted_until);
  const on = Boolean(state?.on);
  const Icon = on ? BellRing : muted ? BellOff : Bell;
  return (
    <div
      role="status"
      aria-label="Sirène"
      className={cn(
        "flex items-center gap-3 rounded-lg border px-3 py-2 text-sm",
        on && "border-destructive/40 bg-destructive/5",
        className,
      )}
    >
      <Icon
        aria-hidden="true"
        className={cn("size-4 shrink-0", on ? "text-destructive animate-pulse" : "text-muted-foreground")}
      />
      <span className={cn("flex-1", !on && "text-muted-foreground")}>
        {status === "loading" && "Sirène…"}
        {status === "error" && "Sirène : état inconnu"}
        {status === "ready" && state && sirenLabel(state)}
      </span>
      {status === "ready" && on && (
        <Button size="sm" variant="outline" disabled={pending} onClick={() => void mute()}>
          Couper 15 min
        </Button>
      )}
      {status === "ready" && muted && (
        <Button size="sm" variant="outline" disabled={pending} onClick={() => void unmute()}>
          Réactiver
        </Button>
      )}
    </div>
  );
}
```

`pages/dashboard.tsx`: `<SirenBar />` rendered just above `<AlertsCard …>` (same column, inside the page's flex column, not inside the link). `alerts-page-content.tsx`: `<SirenBar />` right under the three summary cards.

- [ ] **Step 4: Toolchain, build, commit**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | grep -E "Tests |×"; pnpm build >/dev/null 2>&1; echo "build exit: $?"`
Expected: all pass (+4), build exit 0.

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src && git commit -q -m "$(cat <<'EOF'
feat(frontend): siren bar with « Couper 15 min » / « Réactiver » on the dashboard and /alertes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: README, env example, spec status, live check

**Files:**
- Modify: `README.md`, `backend/.env.example`, `docs/superpowers/specs/2026-10-07-siren-mqtt-design.md`

- [ ] **Step 1: Docs**

README « Alertes » section, append:

```markdown
**Sirène.** L'API publie l'état du buzzer sur le topic MQTT **retenu** `sentinel/cmd/buzzer`
(QoS 1) : `{"on": true, "reason": "gas", "open": 2, "muted_until": null, "at": "…"}`. `on` est vrai
quand une alerte ouverte correspond à `BUZZER_TRIGGERS` (`gas,temperature:high` par défaut ;
`metric` ou `metric:low|high`) et qu'aucune coupure n'est en cours. `GET /api/alerts/siren`,
`POST /api/alerts/siren/mute` (coupe `BUZZER_MUTE_MINUTES`, 15 par défaut),
`DELETE /api/alerts/siren/mute` ; événement WebSocket `siren.state`. L'ESP32 n'a qu'à s'abonner et
lire `on` : exemple Arduino dans `docs/superpowers/specs/2026-10-07-siren-mqtt-design.md`.
```

`.env.example`: `MQTT_BUZZER_TOPIC=sentinel/cmd/buzzer`, `BUZZER_TRIGGERS=gas,temperature:high`, `BUZZER_MUTE_MINUTES=15` with a one-line comment. Spec status → « implémenté le 2026-10-07 ».

- [ ] **Step 2: Live check on the dev stack**

The dev api has `MQTT_HOST=mosquitto`. In one terminal: `docker compose exec mosquitto mosquitto_sub -t 'sentinel/cmd/buzzer' -v` (the retained message arrives at once). Then `cd backend && uv run simulate-sensors --spike --spike-metric gas --interval 2 --base-url http://localhost:8000`: the subscriber prints `on:true … reason gas` within a second of the 6th reading, `on:false` after the burst. In the browser the bar turns red with « Couper 15 min »; clicking it prints `on:false` with `muted_until` on the subscriber.

- [ ] **Step 3: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add README.md backend/.env.example docs && git commit -q -m "$(cat <<'EOF'
docs: siren topic, payload, triggers, mute routes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

## Finish

Whole-branch review, then superpowers:finishing-a-development-branch: fast-forward `develop` and `main`, delete the branch, push both; `make deploy` on the Pi. Hand the contract (topic, payload, Arduino snippet) to the ESP teammate.
