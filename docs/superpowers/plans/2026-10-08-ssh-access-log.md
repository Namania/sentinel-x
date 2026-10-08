# Accès SSH (journal + alerte `ssh`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show every SSH connection to the Pi (accepted with the key's mail, refused with the reason) on a dedicated `/ssh` page, and open one `ssh` alert per IP on refusals, resolved after ten quiet minutes.

**Architecture:** A host agent (`scripts/ssh-log-agent.py`, stdlib only, systemd user service) tails `journalctl -u ssh -o json -f`, enriches the key fingerprint with the comment from `~/.ssh/authorized_keys`, and POSTs each event to `/api/ssh/events` with the device key. The API stores it (`ssh_events`), broadcasts `ssh.event`, and for a refusal opens/increments an `Alert(metric="ssh", device_id="ip:<ip>")` that a background timer resolves after `SSH_ALERT_QUIET_MINUTES`. The front gets a new feature `features/ssh` (page, hook, row) and the alerts feature learns the `ssh` metric and the new `alert.updated` event.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 async / Alembic / pytest (backend), Python 3.13 stdlib (agent on the Pi), React 19 / TS / Tailwind v4 / shadcn / MSW / Vitest (front), sh POSIX + systemd --user (install).

**Spec:** `docs/superpowers/specs/2026-10-08-ssh-access-log-design.md`

## Global Constraints

- Work on branch `ssh-access-log` (cut from `develop`, spec already committed there). Integrate into `develop` only, rebase + fast-forward, never touch `main`.
- Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Backend checks before each commit, from `backend/`: `uv run ruff check src tests && uv run ruff format --check src tests && uv run pytest tests/unit -q`. Integration tests need Postgres on `localhost:5432` (`sentinel`/`sentinel`/`sentinel_test`): start Colima, then `docker compose -f compose.yml -f compose.dev.yml up -d db` from the repo root (its DB is reused by the tests) or `docker run -d --rm --name sentinel-test-pg -e POSTGRES_USER=sentinel -e POSTGRES_PASSWORD=sentinel -e POSTGRES_DB=sentinel_test -p 127.0.0.1:5432:5432 postgres:16-alpine`.
- Frontend checks before each commit, from `frontend/`: `pnpm lint && pnpm typecheck && pnpm exec prettier --check src && pnpm exec vitest run`. The harness resets the cwd between calls: always `cd` in the same command, and use `pnpm --dir /Users/namania/git/sentinel-x/frontend …` if in doubt. `pnpm build | tail` misbehaves under pipefail: run `pnpm build >/dev/null; echo $?`.
- UI copy is French; code, comments and commit messages are English. Labels copied verbatim from the spec: « Accès SSH », « Connexions 24 h », « Refus 24 h », « Dernière acceptée », « clé non acceptée », « utilisateur inconnu », « mot de passe refusé », « trop de tentatives », « Journal SSH indisponible. », « Aucune connexion », « Seules les 500 connexions les plus récentes sont affichées. », « tentatives de connexion refusées ».
- The agent script has no dependency outside the Python standard library and never imports the API package.
- `METRICS` stays the tuple of **sensor** metrics (bounds); `ALERT_METRICS = (*METRICS, "ssh")` is what the siren and the filters know. Default `BUZZER_TRIGGERS` stays `gas,temperature:high`.
- The `ssh` alert: `device_id = "ip:<ip>"`, `direction = "high"`, `threshold = 0.0`, `opened_value = 1.0`, `peak_value` = number of refused attempts, `resolved_value` = that number.

## Review Focus

1. **An IPv6 or scanner IP in `device_id`** (`ip:fe80::1`, 45 chars): `GET /alerts?device_id=ip:fe80::1` must be accepted by the route's pattern and the front must show the IP, not the prefix. Test in Task 4 (`test_alerts_device_filter_accepts_ip_device_ids`) and Task 7 (`ipFromDevice` on an IPv6).
2. **`journalctl` emits `MESSAGE` as a byte array** (non-UTF-8 username probes): the agent must skip the entry and still advance the cursor, never crash. Test in Task 5 (`test_binary_message_is_ignored`).
3. **The API is down during `make deploy`** for a minute: events must arrive later, in order, once, with the cursor only advancing on success. Tests in Task 5 (`test_deliver_retries_with_backoff_without_advancing`, `test_duplicate_is_acknowledged_with_200`) and Task 4 (`re-POST → 200`).
4. **A refusal arrives with a timestamp in the future or weeks old** (Pi clock drift, replayed journal): the quiet timer must still fire within `quiet_minutes` of *now*, not never. Test in Task 3 (`test_a_future_timestamp_does_not_delay_the_resolution`).
5. **An `ssh` alert left open by a crash**: after a restart the API must resolve it `quiet_minutes` later even if the IP never shows again. Test in Task 3 (`test_start_resolves_alerts_left_open_after_a_restart`).

---

### Task 1: SSH event domain, persistence and migration

**Files:**
- Create: `backend/src/app/domain/ssh_event.py`
- Modify: `backend/src/app/domain/repositories.py` (add `SshEventRepository`)
- Modify: `backend/src/app/application/ports/unit_of_work.py` (attribute `ssh_events`)
- Modify: `backend/src/app/infrastructure/db/models.py` (add `SshEventModel`)
- Modify: `backend/src/app/infrastructure/db/repositories.py` (add `SqlAlchemySshEventRepository`)
- Modify: `backend/src/app/infrastructure/db/unit_of_work.py` (wire `ssh_events`)
- Create: `backend/alembic/versions/0006_create_ssh_events.py`
- Modify: `backend/tests/unit/fakes.py` (add `InMemorySshEventRepository`, wire into `InMemoryUnitOfWork`)
- Test: `backend/tests/unit/test_ssh_event_domain.py`, `backend/tests/integration/test_ssh_event_repository.py`

**Interfaces:**
- Produces: `app.domain.ssh_event.SshEvent` (frozen dataclass, fields below), `Outcome = Literal["accepted", "refused"]`, `Reason = Literal["key_rejected", "unknown_user", "bad_password", "too_many_attempts"]`, `SshEventFilter = Literal["accepted", "refused", "all"]`; `SshEventRepository.add(event) -> bool`, `SshEventRepository.list(outcome: SshEventFilter, limit: int) -> list[SshEvent]`; `UnitOfWork.ssh_events`.

- [ ] **Step 1: Write the failing domain test**

`backend/tests/unit/test_ssh_event_domain.py`:

```python
from datetime import UTC, datetime
from uuid import UUID

from app.domain.ssh_event import SshEvent

AT = datetime(2026, 10, 8, 7, 37, 35, tzinfo=UTC)


def test_create_generates_an_id_and_defaults_the_optional_fields():
    event = SshEvent.create(
        journal_id="s=1;i=2", occurred_at=AT, outcome="refused",
        username="root", ip="203.0.113.5", port=51234, reason="unknown_user",
    )
    assert isinstance(event.id, UUID)
    assert (event.method, event.key_fingerprint, event.key_comment) == (None, None, None)
    assert event.reason == "unknown_user"
    assert event.occurred_at == AT


def test_two_events_never_share_an_id():
    kwargs = dict(journal_id="x", occurred_at=AT, outcome="accepted", username="u", ip="1.2.3.4", port=1)
    assert SshEvent.create(**kwargs).id != SshEvent.create(**kwargs).id
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_ssh_event_domain.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.ssh_event'`

- [ ] **Step 3: Write the domain entity**

`backend/src/app/domain/ssh_event.py`:

```python
"""One SSH connection to the Pi, accepted or refused, as sshd journalled it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

Outcome = Literal["accepted", "refused"]
Reason = Literal["key_rejected", "unknown_user", "bad_password", "too_many_attempts"]
SshEventFilter = Literal["accepted", "refused", "all"]


@dataclass(frozen=True, slots=True)
class SshEvent:
    id: UUID
    journal_id: str  # journald __CURSOR: unique, lets the agent replay without duplicates
    occurred_at: datetime
    outcome: Outcome
    username: str
    ip: str
    port: int
    method: str | None
    key_fingerprint: str | None
    key_comment: str | None  # the comment of the key in authorized_keys, usually a mail
    reason: Reason | None

    @classmethod
    def create(
        cls,
        *,
        journal_id: str,
        occurred_at: datetime,
        outcome: Outcome,
        username: str,
        ip: str,
        port: int,
        method: str | None = None,
        key_fingerprint: str | None = None,
        key_comment: str | None = None,
        reason: Reason | None = None,
    ) -> SshEvent:
        return cls(
            id=uuid4(),
            journal_id=journal_id,
            occurred_at=occurred_at,
            outcome=outcome,
            username=username,
            ip=ip,
            port=port,
            method=method,
            key_fingerprint=key_fingerprint,
            key_comment=key_comment,
            reason=reason,
        )
```

- [ ] **Step 4: Run the domain test**

Run: `cd backend && uv run pytest tests/unit/test_ssh_event_domain.py -q`
Expected: `2 passed`

- [ ] **Step 5: Add the repository port and the unit-of-work attribute**

In `backend/src/app/domain/repositories.py`, add the import `from app.domain.ssh_event import SshEvent, SshEventFilter` and, at the end of the file:

```python
class SshEventRepository(ABC):
    @abstractmethod
    async def add(self, event: SshEvent) -> bool:
        """Store the event; False (and nothing written) when its journal_id is already known."""

    @abstractmethod
    async def list(self, outcome: SshEventFilter, limit: int) -> list[SshEvent]:
        """Newest first (occurred_at descending), at most `limit`."""
```

In `backend/src/app/application/ports/unit_of_work.py`, extend the import to `from app.domain.repositories import (AlertRepository, SensorReadingRepository, SshEventRepository, UserRepository)` and add the attribute `ssh_events: SshEventRepository` after `alerts: AlertRepository`.

- [ ] **Step 6: Add the in-memory fake**

In `backend/tests/unit/fakes.py`, import `SshEventRepository` from `app.domain.repositories` and `SshEvent` from `app.domain.ssh_event`, then add before `InMemoryUnitOfWork`:

```python
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
```

and in `InMemoryUnitOfWork.__init__`: `self.ssh_events = InMemorySshEventRepository()`.

- [ ] **Step 7: Write the failing integration test for the SQL repository**

`backend/tests/integration/test_ssh_event_repository.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.ssh_event import SshEvent
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

T0 = datetime(2026, 10, 8, 7, 0, tzinfo=UTC)


def event(journal_id="c1", minutes=0, outcome="accepted") -> SshEvent:
    return SshEvent.create(
        journal_id=journal_id,
        occurred_at=T0 + timedelta(minutes=minutes),
        outcome=outcome,
        username="sentinel-x",
        ip="192.168.0.18",
        port=49513 + minutes,
        method="publickey" if outcome == "accepted" else None,
        key_fingerprint="SHA256:abc" if outcome == "accepted" else None,
        key_comment="mael.namania@gmail.com" if outcome == "accepted" else None,
        reason=None if outcome == "accepted" else "key_rejected",
    )


@pytest.fixture
async def uow(session_factory):
    return SqlAlchemyUnitOfWork(session_factory)


async def test_add_refuses_a_second_event_with_the_same_journal_id(uow):
    async with uow as tx:
        assert await tx.ssh_events.add(event("c1")) is True
        assert await tx.ssh_events.add(event("c1", minutes=1)) is False
        await tx.commit()
    async with uow as tx:
        rows = await tx.ssh_events.list("all", 10)
    assert [r.journal_id for r in rows] == ["c1"]
    assert rows[0].key_comment == "mael.namania@gmail.com"


async def test_list_is_newest_first_filtered_and_limited(uow):
    async with uow as tx:
        for e in (event("a", 0), event("b", 2, "refused"), event("c", 1), event("d", 3, "refused")):
            await tx.ssh_events.add(e)
        await tx.commit()
    async with uow as tx:
        assert [r.journal_id for r in await tx.ssh_events.list("all", 10)] == ["d", "b", "c", "a"]
        assert [r.journal_id for r in await tx.ssh_events.list("refused", 10)] == ["d", "b"]
        assert [r.journal_id for r in await tx.ssh_events.list("accepted", 1)] == ["c"]
```

- [ ] **Step 8: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_ssh_event_repository.py -q`
Expected: FAIL with `AttributeError: 'SqlAlchemyUnitOfWork' object has no attribute 'ssh_events'`

- [ ] **Step 9: Add the model, the SQL repository and the wiring**

In `backend/src/app/infrastructure/db/models.py`, after `AlertModel`:

```python
class SshEventModel(Base):
    __tablename__ = "ssh_events"
    __table_args__ = (
        Index("ix_ssh_events_occurred_at", "occurred_at"),
        Index("uq_ssh_events_journal_id", "journal_id", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    journal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    key_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    key_comment: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

In `backend/src/app/infrastructure/db/repositories.py`: import `SshEventRepository` next to `AlertRepository`, `from app.domain.ssh_event import Outcome, Reason, SshEvent, SshEventFilter`, `SshEventModel` next to `AlertModel`, and append:

```python
def _ssh_event_to_entity(row: SshEventModel) -> SshEvent:
    return SshEvent(
        id=row.id,
        journal_id=row.journal_id,
        occurred_at=row.occurred_at,
        outcome=cast(Outcome, row.outcome),
        username=row.username,
        ip=row.ip,
        port=row.port,
        method=row.method,
        key_fingerprint=row.key_fingerprint,
        key_comment=row.key_comment,
        reason=cast(Reason | None, row.reason),
    )


class SqlAlchemySshEventRepository(SshEventRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: SshEvent) -> bool:
        m = SshEventModel
        exists = await self._session.scalar(select(m.id).where(m.journal_id == event.journal_id))
        if exists is not None:
            return False
        self._session.add(
            SshEventModel(
                id=event.id,
                journal_id=event.journal_id,
                occurred_at=event.occurred_at,
                outcome=event.outcome,
                username=event.username,
                ip=event.ip,
                port=event.port,
                method=event.method,
                key_fingerprint=event.key_fingerprint,
                key_comment=event.key_comment,
                reason=event.reason,
            )
        )
        await self._session.flush()
        return True

    async def list(self, outcome: SshEventFilter, limit: int) -> list[SshEvent]:
        m = SshEventModel
        stmt = select(m)
        if outcome != "all":
            stmt = stmt.where(m.outcome == outcome)
        stmt = stmt.order_by(m.occurred_at.desc()).limit(limit)
        return [_ssh_event_to_entity(r) for r in (await self._session.scalars(stmt)).all()]
```

In `backend/src/app/infrastructure/db/unit_of_work.py`: import `SqlAlchemySshEventRepository` and add `self.ssh_events = SqlAlchemySshEventRepository(self._session)` in `__aenter__`.

- [ ] **Step 10: Write the migration**

`backend/alembic/versions/0006_create_ssh_events.py`:

```python
"""create ssh_events

One row per SSH connection to the Pi (accepted or refused) relayed by the host agent.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08

"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ssh_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("journal_id", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=8), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=True),
        sa.Column("key_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("key_comment", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ssh_events_occurred_at", "ssh_events", ["occurred_at"])
    op.create_index("uq_ssh_events_journal_id", "ssh_events", ["journal_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_ssh_events_journal_id", table_name="ssh_events")
    op.drop_index("ix_ssh_events_occurred_at", table_name="ssh_events")
    op.drop_table("ssh_events")
```

- [ ] **Step 11: Run the repository tests and the whole backend suite**

Run: `cd backend && uv run pytest tests/integration/test_ssh_event_repository.py -q && uv run pytest -q 2>&1 | tail -3`
Expected: `2 passed`, then the whole suite green (unit + integration).

- [ ] **Step 12: Check the migration against a scratch database**

Run (Postgres running): `cd backend && C=$(docker ps --filter publish=5432 --format '{{.Names}}' | head -1); docker exec $C psql -U sentinel -d postgres -q -c "DROP DATABASE IF EXISTS sentinel_mig;" -c "CREATE DATABASE sentinel_mig;" && POSTGRES_HOST=localhost POSTGRES_DB=sentinel_mig POSTGRES_USER=sentinel POSTGRES_PASSWORD=sentinel JWT_SECRET=x-migration-check-0123456789abcdef uv run alembic upgrade head 2>&1 | tail -1 && docker exec $C psql -U sentinel -d sentinel_mig -At -c "\d ssh_events" | head -3 && docker exec $C psql -U sentinel -d postgres -q -c "DROP DATABASE sentinel_mig;"`
Expected: `Running upgrade 0005 -> 0006, create ssh_events` and the `ssh_events` columns listed.

- [ ] **Step 13: Lint and commit**

```bash
cd backend && uv run ruff check src tests && uv run ruff format src tests
cd .. && git add backend && git commit -m "feat(ssh): SshEvent entity, repository and ssh_events table

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: The `ssh` alert metric, siren trigger and setting

**Files:**
- Modify: `backend/src/app/domain/alert.py:12-14`
- Modify: `backend/src/app/domain/siren.py:10-15, 33`
- Modify: `backend/src/app/infrastructure/config.py` (after `buzzer_mute_minutes`)
- Modify: `backend/src/app/presentation/http/alerts.py` (`device_id` query pattern)
- Modify: `backend/.env.example` (after `BUZZER_MUTE_MINUTES`)
- Test: `backend/tests/unit/test_siren_domain.py`, `backend/tests/unit/test_settings.py`

**Interfaces:**
- Produces: `Metric` includes `"ssh"`; `ALERT_METRICS: tuple[Metric, ...]`; `Settings.ssh_alert_quiet_minutes: int`; `REASON_ORDER = ("gas", "ssh", "temperature", "humidity")`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_siren_domain.py`:

```python
def test_ssh_is_a_valid_trigger_ranked_after_gas():
    from app.domain.siren import REASON_ORDER

    assert parse_triggers("ssh") == (Trigger("ssh", None),)
    assert REASON_ORDER.index("gas") < REASON_ORDER.index("ssh") < REASON_ORDER.index("temperature")


def test_an_ssh_alert_rings_only_when_ssh_is_a_trigger():
    ssh_alert = Alert.open(
        device_id="ip:203.0.113.5", metric="ssh", direction="high", threshold=0.0,
        at=datetime(2026, 10, 8, 9, 0, tzinfo=UTC), value=1.0,
    )
    now = datetime(2026, 10, 8, 9, 1, tzinfo=UTC)
    silent = decide([ssh_alert], parse_triggers("gas,temperature:high"), None, now)
    ringing = decide([ssh_alert], parse_triggers("gas,ssh"), None, now)
    assert (silent.on, silent.open) == (False, 1)
    assert (ringing.on, ringing.reason) == (True, "ssh")
```

Append to `backend/tests/unit/test_settings.py`:

```python
def test_ssh_alert_quiet_minutes_defaults_to_ten_and_is_bounded(monkeypatch):
    assert Settings(_env_file=None, jwt_secret="x" * 32).ssh_alert_quiet_minutes == 10
    monkeypatch.setenv("SSH_ALERT_QUIET_MINUTES", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="x" * 32)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_siren_domain.py tests/unit/test_settings.py -q`
Expected: 3 FAIL (`ValueError: unknown metric in BUZZER_TRIGGERS: 'ssh'`, `AttributeError … ssh_alert_quiet_minutes`).

- [ ] **Step 3: Implement**

`backend/src/app/domain/alert.py` lines 12-14 become:

```python
Metric = Literal["temperature", "humidity", "gas", "ssh"]
Direction = Literal["low", "high"]
# The sensor metrics: they have bounds, RecordReading opens and closes their alerts.
METRICS: tuple[Metric, ...] = ("temperature", "humidity", "gas")
# Every metric an alert can carry: "ssh" (refused SSH connections, one alert per IP) has no
# bound; application/ssh/record.py opens, worsens and resolves it.
ALERT_METRICS: tuple[Metric, ...] = (*METRICS, "ssh")
```

`backend/src/app/domain/siren.py`: import `ALERT_METRICS` instead of `METRICS`; `REASON_ORDER: tuple[Metric, ...] = ("gas", "ssh", "temperature", "humidity")`; in `parse_triggers`, `if metric not in ALERT_METRICS:`.

`backend/src/app/infrastructure/config.py`, after `buzzer_mute_minutes`:

```python
    # Refused SSH connections open one alert per IP; it closes after this long without a new one.
    ssh_alert_quiet_minutes: int = Field(default=10, ge=1, le=1440)
```

`backend/src/app/presentation/http/alerts.py`, in `list_alerts`: `device_id: Annotated[str | None, Query(pattern=r"^[a-z0-9.:-]{1,64}$")] = None,` (IPs carry dots and colons).

`backend/.env.example`, after `BUZZER_MUTE_MINUTES=15`:

```
# Refused SSH connections (relayed by scripts/ssh-log-agent.py) open one alert per IP, closed
# after this many quiet minutes. Add `ssh` to BUZZER_TRIGGERS to ring the buzzer on them.
SSH_ALERT_QUIET_MINUTES=10
```

- [ ] **Step 4: Run the unit suite**

Run: `cd backend && uv run pytest tests/unit -q 2>&1 | tail -2`
Expected: all passed (the `intruder` rejection test still passes: `intruder` is not in `ALERT_METRICS`).

- [ ] **Step 5: Lint and commit**

```bash
cd backend && uv run ruff check src tests && uv run ruff format src tests
cd .. && git add backend && git commit -m "feat(alerts): ssh metric, siren trigger and SSH_ALERT_QUIET_MINUTES

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `RecordSshEvent` service with the quiet timer

**Files:**
- Create: `backend/src/app/application/ssh/__init__.py` (empty), `backend/src/app/application/ssh/dtos.py`, `backend/src/app/application/ssh/record.py`
- Test: `backend/tests/unit/test_record_ssh_event.py`

**Interfaces:**
- Consumes: `UnitOfWork.ssh_events` (Task 1), `Alert`, `AlertOutput.from_entity(alert).to_event()`, `EventBroadcaster.broadcast(dict)`, `MAX_FUTURE_DRIFT`/`MAX_AGE` from `app.application.sensors.record`.
- Produces: `SshEventInput` (frozen dataclass: `journal_id, occurred_at, outcome, username, ip, port, method=None, key_fingerprint=None, key_comment=None, reason=None`), `ssh_event_to_dict(event: SshEvent) -> dict`, `RecordSshEvent(uow_factory, broadcaster, on_alerts_changed=None, quiet_minutes=10, clock=_utc_now, sleep=asyncio.sleep)` with `async start()`, `async record(data) -> tuple[SshEvent, bool]`, `close()`; events `ssh.event`, `alert.opened`, `alert.updated`, `alert.resolved`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_record_ssh_event.py`:

```python
import asyncio
from datetime import UTC, datetime, timedelta

from app.application.ssh.record import RecordSshEvent, SshEventInput
from app.domain.alert import Alert
from tests.unit.fakes import InMemoryUnitOfWork, RecordingBroadcaster

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class Hook:
    def __init__(self, fail=False) -> None:
        self.calls = 0
        self.fail = fail

    async def __call__(self) -> None:
        self.calls += 1
        if self.fail:
            raise ConnectionError("broker down")


def build(hook: Hook | None = None, quiet_minutes=10):
    uow = InMemoryUnitOfWork()
    bus = RecordingBroadcaster()
    clock = Clock()
    sleeps: list[float] = []
    wakes: list[asyncio.Future[None]] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        wakes.append(future)
        await future

    service = RecordSshEvent(
        uow_factory=lambda: uow, broadcaster=bus, on_alerts_changed=hook,
        quiet_minutes=quiet_minutes, clock=clock, sleep=sleep,
    )
    return service, uow, bus, clock, sleeps, wakes


def refused(journal_id="c1", ip="203.0.113.5", at=NOW, reason="key_rejected") -> SshEventInput:
    return SshEventInput(
        journal_id=journal_id, occurred_at=at, outcome="refused", username="root",
        ip=ip, port=51234, reason=reason,
    )


def accepted(journal_id="a1", at=NOW) -> SshEventInput:
    return SshEventInput(
        journal_id=journal_id, occurred_at=at, outcome="accepted", username="sentinel-x",
        ip="192.168.0.18", port=49513, method="publickey",
        key_fingerprint="SHA256:Wqjh", key_comment="mael.namania@gmail.com",
    )


def types(bus) -> list[str]:
    return [e["type"] for e in bus.broadcasts]


async def test_an_accepted_connection_is_stored_and_broadcast_without_an_alert():
    service, uow, bus, _, _, _ = build(Hook())
    event, created = await service.record(accepted())
    assert created is True
    assert [e.journal_id for e in uow.ssh_events.events] == ["a1"]
    assert uow.alerts.alerts == []
    assert types(bus) == ["ssh.event"]
    assert bus.broadcasts[0]["data"]["key_comment"] == "mael.namania@gmail.com"
    assert bus.broadcasts[0]["data"]["occurred_at"] == "2026-10-08T09:00:00Z"
    assert bus.broadcasts[0]["data"]["id"] == str(event.id)


async def test_a_refusal_opens_one_alert_per_ip_and_wakes_the_siren():
    hook = Hook()
    service, uow, bus, _, sleeps, _ = build(hook)
    await service.record(refused())
    await asyncio.sleep(0)
    (alert,) = uow.alerts.alerts
    assert (alert.device_id, alert.metric, alert.direction) == ("ip:203.0.113.5", "ssh", "high")
    assert (alert.threshold, alert.opened_value, alert.peak_value) == (0.0, 1.0, 1.0)
    assert alert.opened_at == NOW
    assert types(bus) == ["ssh.event", "alert.opened"]
    assert hook.calls == 1
    assert sleeps == [10 * 60]


async def test_a_second_refusal_from_the_same_ip_increments_the_alert():
    hook = Hook()
    service, uow, bus, clock, sleeps, _ = build(hook)
    await service.record(refused("c1"))
    clock.now = NOW + timedelta(minutes=3)
    await service.record(refused("c2", at=clock.now))
    await asyncio.sleep(0)
    assert len(uow.alerts.alerts) == 1
    assert uow.alerts.alerts[0].peak_value == 2.0
    assert types(bus) == ["ssh.event", "alert.opened", "ssh.event", "alert.updated"]
    assert bus.broadcasts[-1]["data"]["peak_value"] == 2.0
    assert hook.calls == 1  # the siren only cares about open/close
    assert sleeps[-1] == 10 * 60  # re-armed from the latest attempt


async def test_refusals_from_two_ips_open_two_alerts():
    service, uow, _, _, _, _ = build()
    await service.record(refused("c1", ip="203.0.113.5"))
    await service.record(refused("c2", ip="198.51.100.7"))
    assert sorted(a.device_id for a in uow.alerts.alerts) == ["ip:198.51.100.7", "ip:203.0.113.5"]


async def test_the_alert_resolves_after_quiet_minutes():
    hook = Hook()
    service, uow, bus, clock, _, wakes = build(hook)
    await service.record(refused("c1"))
    await service.record(refused("c2", at=NOW + timedelta(minutes=1)))
    await asyncio.sleep(0)
    clock.now = NOW + timedelta(minutes=11)
    wakes[-1].set_result(None)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    (alert,) = uow.alerts.alerts
    assert alert.resolved_at == clock.now
    assert alert.resolved_value == 2.0
    assert types(bus)[-1] == "alert.resolved"
    assert hook.calls == 2


async def test_a_refusal_during_the_quiet_window_postpones_the_resolution():
    service, uow, _, clock, sleeps, wakes = build()
    await service.record(refused("c1"))
    await asyncio.sleep(0)
    clock.now = NOW + timedelta(minutes=9)
    await service.record(refused("c2", at=clock.now))
    await asyncio.sleep(0)
    assert sleeps[-1] == 10 * 60
    # The first timer was cancelled: resolving it would be wrong.
    assert wakes[0].cancelled() or not wakes[0].done()
    clock.now = NOW + timedelta(minutes=10, seconds=30)
    wakes[-1].set_result(None)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert uow.alerts.alerts[0].is_open  # 9 min + 1:30 < 10 min of quiet
    assert sleeps[-1] > 0  # re-armed for the remaining time


async def test_a_future_timestamp_does_not_delay_the_resolution():
    service, uow, _, clock, sleeps, wakes = build()
    await service.record(refused("c1", at=NOW + timedelta(days=2)))
    await asyncio.sleep(0)
    assert sleeps == [10 * 60]  # measured from now, not from the bogus timestamp
    clock.now = NOW + timedelta(minutes=10)
    wakes[-1].set_result(None)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not uow.alerts.alerts[0].is_open


async def test_a_duplicate_journal_id_is_acknowledged_but_changes_nothing():
    service, uow, bus, _, _, _ = build()
    await service.record(refused("c1"))
    event, created = await service.record(refused("c1"))
    assert created is False
    assert event.journal_id == "c1"
    assert len(uow.ssh_events.events) == 1
    assert uow.alerts.alerts[0].peak_value == 1.0
    assert types(bus) == ["ssh.event", "alert.opened"]


async def test_start_resolves_alerts_left_open_after_a_restart():
    service, uow, bus, clock, sleeps, wakes = build()
    stale = Alert.open(
        device_id="ip:203.0.113.5", metric="ssh", direction="high", threshold=0.0,
        at=NOW - timedelta(hours=5), value=3.0,
    )
    await uow.alerts.add(stale)
    await service.start()
    await asyncio.sleep(0)
    assert sleeps == [10 * 60]
    clock.now = NOW + timedelta(minutes=10)
    wakes[-1].set_result(None)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert uow.alerts.alerts[0].resolved_value == 3.0
    assert types(bus) == ["alert.resolved"]


async def test_a_failing_hook_does_not_lose_the_event():
    service, uow, bus, _, _, _ = build(Hook(fail=True))
    _, created = await service.record(refused("c1"))
    assert created is True
    assert len(uow.ssh_events.events) == 1
    assert types(bus) == ["ssh.event", "alert.opened"]


async def test_close_cancels_the_timer():
    service, _, _, _, _, wakes = build()
    await service.record(refused("c1"))
    await asyncio.sleep(0)
    service.close()
    await asyncio.sleep(0)
    assert wakes[0].cancelled()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_record_ssh_event.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.ssh'`

- [ ] **Step 3: Write the DTO helper**

`backend/src/app/application/ssh/dtos.py`:

```python
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC
from typing import Any

from app.domain.ssh_event import SshEvent


def ssh_event_to_dict(event: SshEvent) -> dict[str, Any]:
    """JSON-safe body, shared by the REST response and the `ssh.event` WebSocket event."""
    data = asdict(event)
    data["id"] = str(event.id)
    data["occurred_at"] = event.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return data
```

- [ ] **Step 4: Write the service**

`backend/src/app/application/ssh/record.py`:

```python
"""Store SSH connections relayed by the host agent; refusals open one `ssh` alert per IP.

The alert counts the refused attempts (`peak_value`) and resolves itself once the IP has been
quiet for `quiet_minutes`: a single background timer sleeps until the earliest deadline, resolves
what is due, and re-arms. Like the siren's wake-up, every refusal reschedules it."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.application.alerts.dtos import AlertOutput
from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.ports.unit_of_work import UnitOfWork
from app.application.sensors.record import MAX_AGE, MAX_FUTURE_DRIFT
from app.application.ssh.dtos import ssh_event_to_dict
from app.domain.alert import Alert
from app.domain.ssh_event import Outcome, Reason, SshEvent

logger = logging.getLogger(__name__)

EVENT_TYPE = "ssh.event"
DEVICE_PREFIX = "ip:"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SshEventInput:
    journal_id: str
    occurred_at: datetime
    outcome: Outcome
    username: str
    ip: str
    port: int
    method: str | None = None
    key_fingerprint: str | None = None
    key_comment: str | None = None
    reason: Reason | None = None


class RecordSshEvent:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        broadcaster: EventBroadcaster,
        on_alerts_changed: Callable[[], Awaitable[None]] | None = None,
        quiet_minutes: int = 10,
        clock: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._uow_factory = uow_factory
        self._broadcaster = broadcaster
        self._on_alerts_changed = on_alerts_changed
        self._quiet = timedelta(minutes=quiet_minutes)
        self._clock = clock
        self._sleep = sleep
        self._last_attempt: dict[str, datetime] = {}  # ip → last refused attempt (≤ now)
        self._lock = asyncio.Lock()
        self._timer: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """After a restart: the open `ssh` alerts resolve `quiet_minutes` from now if silent."""
        now = self._clock()
        async with self._uow_factory() as uow:
            open_alerts = await uow.alerts.list("open", None, 500)
        for alert in open_alerts:
            if alert.metric == "ssh" and alert.device_id.startswith(DEVICE_PREFIX):
                self._last_attempt.setdefault(alert.device_id[len(DEVICE_PREFIX) :], now)
        self._arm()

    def close(self) -> None:
        self._cancel_timer()

    async def record(self, data: SshEventInput) -> tuple[SshEvent, bool]:
        """Store the event; returns (event, created). A duplicate journal_id changes nothing."""
        now = self._clock()
        event = SshEvent.create(
            journal_id=data.journal_id,
            occurred_at=self._plausible(data.occurred_at, now),
            outcome=data.outcome,
            username=data.username,
            ip=data.ip,
            port=data.port,
            method=data.method,
            key_fingerprint=data.key_fingerprint,
            key_comment=data.key_comment,
            reason=data.reason,
        )
        alert_event: tuple[str, Alert] | None = None
        async with self._lock:
            async with self._uow_factory() as uow:
                created = await uow.ssh_events.add(event)
                if not created:
                    await uow.commit()
                    return event, False
                if event.outcome == "refused":
                    alert_event = await self._count_refusal(uow, event)
                    self._last_attempt[event.ip] = min(event.occurred_at, now)
                await uow.commit()
        await self._broadcaster.broadcast({"type": EVENT_TYPE, "data": ssh_event_to_dict(event)})
        if alert_event is not None:
            kind, alert = alert_event
            await self._broadcaster.broadcast(
                {"type": kind, "data": AlertOutput.from_entity(alert).to_event()}
            )
            if kind == "alert.opened":
                await self._notify_alerts_changed()
            self._arm()
        return event, True

    async def _count_refusal(self, uow: UnitOfWork, event: SshEvent) -> tuple[str, Alert]:
        device_id = f"{DEVICE_PREFIX}{event.ip}"
        current = await uow.alerts.open_for(device_id, "ssh")
        if current is None:
            opened = Alert.open(
                device_id=device_id,
                metric="ssh",
                direction="high",
                threshold=0.0,
                at=event.occurred_at,
                value=1.0,
            )
            await uow.alerts.add(opened)
            return "alert.opened", opened
        worse = current.worsen(current.peak_value + 1)
        await uow.alerts.save(worse)
        return "alert.updated", worse

    async def _resolve_quiet(self) -> None:
        now = self._clock()
        due = [ip for ip, last in self._last_attempt.items() if last + self._quiet <= now]
        if not due:
            return
        resolved: list[Alert] = []
        async with self._lock:
            async with self._uow_factory() as uow:
                for ip in due:
                    current = await uow.alerts.open_for(f"{DEVICE_PREFIX}{ip}", "ssh")
                    if current is not None:
                        alert = current.resolve(at=now, value=current.peak_value)
                        await uow.alerts.save(alert)
                        resolved.append(alert)
                    self._last_attempt.pop(ip, None)
                await uow.commit()
        for alert in resolved:
            await self._broadcaster.broadcast(
                {"type": "alert.resolved", "data": AlertOutput.from_entity(alert).to_event()}
            )
        if resolved:
            await self._notify_alerts_changed()

    def _arm(self) -> None:
        self._cancel_timer()
        if not self._last_attempt:
            return
        deadline = min(self._last_attempt.values()) + self._quiet
        delay = max(0.0, (deadline - self._clock()).total_seconds())

        async def wake_up() -> None:
            await self._sleep(delay)
            try:
                await self._resolve_quiet()
            except Exception:  # noqa: BLE001 - never leave an alert open because of one error
                logger.exception("ssh alerts: resolving quiet IPs failed")
            self._arm()

        self._timer = asyncio.create_task(wake_up(), name="ssh-alerts-quiet-timer")

    def _cancel_timer(self) -> None:
        task, self._timer = self._timer, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _notify_alerts_changed(self) -> None:
        if self._on_alerts_changed is None:
            return
        try:
            await self._on_alerts_changed()
        except Exception:  # noqa: BLE001 - the event is stored; the siren catches up later
            logger.exception("alert change hook failed")

    @staticmethod
    def _plausible(occurred_at: datetime, now: datetime) -> datetime:
        moment = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
        moment = moment.astimezone(UTC)
        if moment > now + MAX_FUTURE_DRIFT or moment < now - MAX_AGE:
            return now
        return moment
```

Note for `test_a_future_timestamp_does_not_delay_the_resolution`: a timestamp two days ahead is replaced by `now` by `_plausible`, and `_last_attempt` is capped at `now` anyway. Note for `_arm()` called from inside `wake_up`: `_cancel_timer` skips the current task, exactly like the siren.

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest tests/unit/test_record_ssh_event.py -q`
Expected: `11 passed`. If `test_a_refusal_during_the_quiet_window_postpones_the_resolution` fails on `sleeps[-1] > 0`, check that `_arm()` runs after `_resolve_quiet()` in `wake_up` (it must re-arm for the remaining 8:30).

- [ ] **Step 6: Lint and commit**

```bash
cd backend && uv run ruff check src tests && uv run ruff format src tests && uv run pytest tests/unit -q | tail -1
cd .. && git add backend && git commit -m "feat(ssh): RecordSshEvent opens one ssh alert per IP and resolves it after quiet minutes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: HTTP routes and app wiring

**Files:**
- Create: `backend/src/app/presentation/http/ssh.py`
- Modify: `backend/src/app/presentation/dependencies.py` (`get_ssh_access`, `SshAccessDep`)
- Modify: `backend/src/app/presentation/main.py` (state, lifespan, router)
- Test: `backend/tests/integration/test_ssh_http.py`, `backend/tests/integration/test_alerts_http.py`

**Interfaces:**
- Consumes: `RecordSshEvent`, `SshEventInput`, `ssh_event_to_dict` (Task 3); `DeviceKeyDep`, `CurrentUserIdDep`, `UowDep`.
- Produces: `POST /ssh/events` (201 created / 200 duplicate), `GET /ssh/events?outcome=all|accepted|refused&limit=1..500`.

- [ ] **Step 1: Write the failing integration tests**

`backend/tests/integration/test_ssh_http.py`:

```python
from tests.integration.conftest import DEVICE_HEADERS, create_user_and_login

ACCEPTED = {
    "journal_id": "s=aa;i=1",
    "occurred_at": "2026-10-08T07:37:35.412Z",
    "outcome": "accepted",
    "username": "sentinel-x",
    "ip": "192.168.0.18",
    "port": 49513,
    "method": "publickey",
    "key_fingerprint": "SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls",
    "key_comment": "claude-audit@mac-namania",
    "reason": None,
}
REFUSED = {
    "journal_id": "s=aa;i=2",
    "occurred_at": "2026-10-08T07:38:01Z",
    "outcome": "refused",
    "username": "root",
    "ip": "203.0.113.5",
    "port": 51234,
    "reason": "key_rejected",
}


def auth(client):
    return {"Authorization": f"Bearer {create_user_and_login(client)['access_token']}"}


def test_posting_requires_the_device_key_and_reading_requires_a_token(client):
    assert client.post("/ssh/events", json=ACCEPTED).status_code == 401
    assert client.get("/ssh/events").status_code == 401


def test_invalid_bodies_are_refused(client):
    assert client.post("/ssh/events", json={**REFUSED, "reason": None}, headers=DEVICE_HEADERS).status_code == 422
    assert client.post("/ssh/events", json={**ACCEPTED, "reason": "unknown_user"}, headers=DEVICE_HEADERS).status_code == 422
    assert client.post("/ssh/events", json={**REFUSED, "port": 70000}, headers=DEVICE_HEADERS).status_code == 422
    assert client.post("/ssh/events", json={**REFUSED, "ip": "x" * 46}, headers=DEVICE_HEADERS).status_code == 422
    assert client.get("/ssh/events?outcome=bogus", headers=auth(client)).status_code == 422


def test_an_accepted_connection_is_stored_once_and_listed(client):
    headers = auth(client)
    first = client.post("/ssh/events", json=ACCEPTED, headers=DEVICE_HEADERS)
    assert first.status_code == 201, first.text
    assert first.json()["key_comment"] == "claude-audit@mac-namania"
    assert first.json()["occurred_at"] == "2026-10-08T07:37:35.412000Z"
    again = client.post("/ssh/events", json=ACCEPTED, headers=DEVICE_HEADERS)
    assert again.status_code == 200
    rows = client.get("/ssh/events", headers=headers).json()
    assert len(rows) == 1 and rows[0]["journal_id"] == "s=aa;i=1"
    assert client.get("/alerts", headers=headers).json() == []


def test_a_refusal_opens_an_ssh_alert_for_the_ip(client):
    headers = auth(client)
    assert client.post("/ssh/events", json=REFUSED, headers=DEVICE_HEADERS).status_code == 201
    alerts = client.get("/alerts?status=open", headers=headers).json()
    assert len(alerts) == 1
    assert (alerts[0]["metric"], alerts[0]["device_id"], alerts[0]["peak_value"]) == ("ssh", "ip:203.0.113.5", 1.0)
    assert client.get("/alerts?device_id=ip:203.0.113.5", headers=headers).json()[0]["id"] == alerts[0]["id"]
    assert client.post("/ssh/events", json={**REFUSED, "journal_id": "s=aa;i=3"}, headers=DEVICE_HEADERS).status_code == 201
    assert client.get("/alerts?status=open", headers=headers).json()[0]["peak_value"] == 2.0
    refused = client.get("/ssh/events?outcome=refused", headers=headers).json()
    assert [r["journal_id"] for r in refused] == ["s=aa;i=3", "s=aa;i=2"]
    assert client.get("/ssh/events?outcome=accepted", headers=headers).json() == []


def test_events_reach_the_websocket(client):
    tokens = create_user_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        client.post("/ssh/events", json={**ACCEPTED, "journal_id": "s=ws;i=1"}, headers=DEVICE_HEADERS)
        event = ws.receive_json()
        assert event["type"] == "ssh.event"
        assert event["data"]["ip"] == "192.168.0.18"
        client.post("/ssh/events", json={**REFUSED, "journal_id": "s=ws;i=2", "ip": "198.51.100.9"}, headers=DEVICE_HEADERS)
        assert ws.receive_json()["type"] == "ssh.event"
        opened = ws.receive_json()
        assert opened["type"] == "alert.opened"
        assert opened["data"]["device_id"] == "ip:198.51.100.9"
        assert ws.receive_json()["type"] == "siren.state"  # one more open alert, siren stays off
        client.post("/ssh/events", json={**REFUSED, "journal_id": "s=ws;i=3", "ip": "198.51.100.9"}, headers=DEVICE_HEADERS)
        assert ws.receive_json()["type"] == "ssh.event"
        updated = ws.receive_json()
        assert updated["type"] == "alert.updated"
        assert updated["data"]["peak_value"] == 2.0
```

Append to `backend/tests/integration/test_alerts_http.py`:

```python
def test_alerts_device_filter_accepts_ip_device_ids(client):
    headers = auth(client)
    assert client.get("/alerts?device_id=ip:fe80::1", headers=headers).status_code == 200
    assert client.get("/alerts?device_id=ip:203.0.113.5", headers=headers).json() == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/integration/test_ssh_http.py tests/integration/test_alerts_http.py -q 2>&1 | tail -3`
Expected: the `test_ssh_http` tests FAIL with `404` status codes; `test_alerts_device_filter_accepts_ip_device_ids` PASSES already (pattern changed in Task 2).

- [ ] **Step 3: Write the route module**

`backend/src/app/presentation/http/ssh.py`:

```python
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field, model_validator

from app.application.ssh.dtos import ssh_event_to_dict
from app.application.ssh.record import SshEventInput
from app.domain.ssh_event import Outcome, Reason, SshEvent, SshEventFilter
from app.presentation.dependencies import CurrentUserIdDep, DeviceKeyDep, SshAccessDep, UowDep

router = APIRouter(prefix="/ssh", tags=["ssh"])


class SshEventRequest(BaseModel):
    """What scripts/ssh-log-agent.py sends for one sshd journal line."""

    journal_id: str = Field(min_length=1, max_length=255)
    occurred_at: datetime
    outcome: Outcome
    username: str = Field(min_length=1, max_length=64)
    ip: str = Field(min_length=1, max_length=45)
    port: int = Field(ge=1, le=65535)
    method: str | None = Field(default=None, max_length=32)
    key_fingerprint: str | None = Field(default=None, max_length=64)
    key_comment: str | None = Field(default=None, max_length=255)
    reason: Reason | None = None

    @model_validator(mode="after")
    def _reason_matches_outcome(self) -> "SshEventRequest":
        if self.outcome == "refused" and self.reason is None:
            raise ValueError("a refused connection needs a reason")
        if self.outcome == "accepted" and self.reason is not None:
            raise ValueError("an accepted connection has no reason")
        return self

    def to_input(self) -> SshEventInput:
        return SshEventInput(**self.model_dump())


class SshEventResponse(BaseModel):
    id: UUID
    journal_id: str
    occurred_at: datetime
    outcome: Outcome
    username: str
    ip: str
    port: int
    method: str | None
    key_fingerprint: str | None
    key_comment: str | None
    reason: Reason | None

    @classmethod
    def from_entity(cls, event: SshEvent) -> "SshEventResponse":
        return cls(**ssh_event_to_dict(event))


@router.post(
    "/events",
    status_code=status.HTTP_201_CREATED,
    response_model=SshEventResponse,
    summary="Enregistre une connexion SSH relayée par l'agent du Pi",
    description="Authentification par l'en-tête `X-Device-Key` (réglage `DEVICE_API_KEY`). "
    "Stockée puis diffusée sur le WebSocket (`ssh.event`) ; un refus ouvre ou incrémente l'alerte "
    "`ssh` de l'IP, résolue après `SSH_ALERT_QUIET_MINUTES` sans nouvelle tentative. Un "
    "`journal_id` déjà connu répond 200 sans rien changer.",
)
async def post_event(
    body: SshEventRequest, _: DeviceKeyDep, ssh_access: SshAccessDep, response: Response
) -> SshEventResponse:
    event, created = await ssh_access.record(body.to_input())
    if not created:
        response.status_code = status.HTTP_200_OK
    return SshEventResponse.from_entity(event)


@router.get(
    "/events",
    response_model=list[SshEventResponse],
    summary="Connexions SSH au Pi, les plus récentes d'abord",
)
async def list_events(
    _: CurrentUserIdDep,
    uow: UowDep,
    outcome: Annotated[SshEventFilter, Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SshEventResponse]:
    async with uow as tx:
        events = await tx.ssh_events.list(outcome, limit)
    return [SshEventResponse.from_entity(e) for e in events]
```

- [ ] **Step 4: Wire the dependency and the app**

`backend/src/app/presentation/dependencies.py`: import `from app.application.ssh.record import RecordSshEvent`; add after `get_siren`:

```python
def get_ssh_access(conn: HTTPConnection) -> RecordSshEvent:
    return conn.app.state.ssh_access
```

and `SshAccessDep = Annotated[RecordSshEvent, Depends(get_ssh_access)]` after `SirenDep`.

`backend/src/app/presentation/main.py`:
- import `from app.application.ssh.record import RecordSshEvent` and add `ssh` to the `from app.presentation.http import …` line;
- after `app.state.siren = Siren(...)`:

```python
    app.state.ssh_access = RecordSshEvent(
        uow_factory=lambda: SqlAlchemyUnitOfWork(app.state.session_factory),
        broadcaster=app.state.hub,
        on_alerts_changed=app.state.siren.refresh,
        quiet_minutes=settings.ssh_alert_quiet_minutes,
    )
```

- in `lifespan`, after `await _announce_siren(app)`: `await _start_ssh_access(app)`; in the `finally`, before `app.state.siren.close()`: `app.state.ssh_access.close()`;
- `app.include_router(ssh.router)` after `alerts.router`;
- add the helper next to `_announce_siren`:

```python
async def _start_ssh_access(app: FastAPI) -> None:
    """Arm the quiet timer for `ssh` alerts left open by a previous run."""
    try:
        await app.state.ssh_access.start()
    except Exception:  # noqa: BLE001 - the database may not be ready; the first event arms it
        logger.warning("ssh alerts: open alerts not reloaded at start", exc_info=True)
```

- [ ] **Step 5: Run the integration suite**

Run: `cd backend && uv run pytest tests/integration -q 2>&1 | tail -3`
Expected: all passed, including the 5 new `test_ssh_http` tests. If `test_events_reach_the_websocket` sees no `siren.state` after `alert.opened`, check that `on_alerts_changed=app.state.siren.refresh` is wired: the open count changed, so the siren announces.

- [ ] **Step 6: Lint, run everything and commit**

```bash
cd backend && uv run ruff check src tests && uv run ruff format src tests && uv run pytest -q 2>&1 | tail -1
cd .. && git add backend && git commit -m "feat(ssh): POST/GET /ssh/events, ssh.event and alert.updated on the WebSocket

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: The host agent `scripts/ssh-log-agent.py`

**Files:**
- Create: `scripts/ssh-log-agent.py`
- Test: `backend/tests/unit/test_ssh_log_agent.py`

**Interfaces:**
- Consumes: `POST {api_url}/ssh/events` (Task 4) with the JSON body of the spec.
- Produces: functions `parse_message(message: str) -> dict | None`, `event_from_entry(entry: dict, comments: dict[str, str | None]) -> Event | None`, `parse_keygen_output(text: str) -> dict[str, str | None]`, classes `AuthorizedKeys(path, run=subprocess.run)` with `.comments()`, `RefusalMemory(ttl_seconds=120.0, clock=time.monotonic)` with `.first_time(ip, port) -> bool`, `ApiClient(base_url, device_key, opener=urllib.request.urlopen, timeout=5.0)` with `.post(event) -> int`, `CursorStore(path)` with `.read()/.write()`, `deliver(client, event, sleep=time.sleep) -> bool`, `journal_command(unit, cursor, first_run_since) -> list[str]`, `handle_entry(entry, keys, memory, client, cursors) -> Event | None`, `config_from_env(env) -> Config`, `run(config)`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_ssh_log_agent.py`:

```python
"""The host agent lives outside the API package: load it from scripts/ by path."""

import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

AGENT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "ssh-log-agent.py"
spec = importlib.util.spec_from_file_location("ssh_log_agent", AGENT_PATH)
assert spec is not None and spec.loader is not None
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

ACCEPTED_LINE = (
    "Accepted publickey for sentinel-x from 192.168.0.18 port 49513 ssh2: "
    "ED25519 SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls"
)
KEYGEN_OUTPUT = (
    "4096 SHA256:EfqGKQMTw+nb+BML5rZY5l1jBvXSKm6zQ5kBz/KaFkY mael.namania@gmail.com (RSA)\n"
    "256 SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls claude-audit@mac-namania (ED25519)\n"
    "256 SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA no comment (ED25519)\n"
)
COMMENTS = agent.parse_keygen_output(KEYGEN_OUTPUT)


def entry(message, cursor="s=1;i=7", micros="1759909055412000"):
    return {"MESSAGE": message, "__CURSOR": cursor, "__REALTIME_TIMESTAMP": micros, "_PID": "24124"}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            ACCEPTED_LINE,
            {"outcome": "accepted", "username": "sentinel-x", "ip": "192.168.0.18", "port": 49513,
             "method": "publickey", "key_fingerprint": "SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls", "reason": None},
        ),
        (
            "Accepted keyboard-interactive/pam for pi from 10.0.0.2 port 1 ssh2",
            {"outcome": "accepted", "username": "pi", "ip": "10.0.0.2", "port": 1,
             "method": "keyboard-interactive", "key_fingerprint": None, "reason": None},
        ),
        (
            "Connection closed by authenticating user root 203.0.113.5 port 51234 [preauth]",
            {"outcome": "refused", "username": "root", "ip": "203.0.113.5", "port": 51234,
             "method": None, "key_fingerprint": None, "reason": "key_rejected"},
        ),
        (
            "Connection closed by invalid user admin 203.0.113.5 port 51235 [preauth]",
            {"outcome": "refused", "username": "admin", "ip": "203.0.113.5", "port": 51235,
             "method": None, "key_fingerprint": None, "reason": "unknown_user"},
        ),
        (
            "Failed password for invalid user admin from 203.0.113.5 port 51236 ssh2",
            {"outcome": "refused", "username": "admin", "ip": "203.0.113.5", "port": 51236,
             "method": "password", "key_fingerprint": None, "reason": "bad_password"},
        ),
        (
            "Failed password for sentinel-x from 203.0.113.5 port 51237 ssh2",
            {"outcome": "refused", "username": "sentinel-x", "ip": "203.0.113.5", "port": 51237,
             "method": "password", "key_fingerprint": None, "reason": "bad_password"},
        ),
        (
            "Disconnecting authenticating user root 203.0.113.5 port 51238: Too many authentication failures [preauth]",
            {"outcome": "refused", "username": "root", "ip": "203.0.113.5", "port": 51238,
             "method": None, "key_fingerprint": None, "reason": "too_many_attempts"},
        ),
    ],
)
def test_recognised_lines(message, expected):
    assert agent.parse_message(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "pam_unix(sshd:session): session opened for user sentinel-x(uid=1000) by sentinel-x(uid=0)",
        "pam_unix(sshd:session): session closed for user sentinel-x",
        "Invalid user admin from 203.0.113.5 port 51235",
        "Received disconnect from 192.168.0.18 port 49513:11: disconnected by user",
        "Disconnected from user sentinel-x 192.168.0.18 port 49513",
        "Connection closed by 203.0.113.5 port 44444 [preauth]",
        "banner exchange: Connection from 203.0.113.5 port 44445: invalid format",
        "Unable to negotiate with 203.0.113.5 port 44446: no matching key exchange method found. [preauth]",
        "Server listening on 0.0.0.0 port 26655.",
    ],
)
def test_ignored_lines(message):
    assert agent.parse_message(message) is None


def test_event_from_entry_adds_time_cursor_and_the_key_comment():
    event = agent.event_from_entry(entry(ACCEPTED_LINE), COMMENTS)
    assert event.journal_id == "s=1;i=7"
    assert event.occurred_at == "2026-10-08T07:37:35.412Z"
    assert event.key_comment == "claude-audit@mac-namania"
    assert event.outcome == "accepted"


def test_event_from_entry_prefers_the_source_timestamp_and_truncates():
    long_user = "u" * 80
    e = entry(f"Connection closed by invalid user {long_user} 203.0.113.5 port 1 [preauth]")
    e["_SOURCE_REALTIME_TIMESTAMP"] = "1759909056000000"
    event = agent.event_from_entry(e, {})
    assert event.occurred_at == "2026-10-08T07:37:36.000Z"
    assert len(event.username) == 64


def test_unknown_fingerprint_gives_no_comment():
    line = ACCEPTED_LINE.replace("WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls", "Zzzz")
    assert agent.event_from_entry(entry(line), COMMENTS).key_comment is None


def test_binary_message_is_ignored():
    assert agent.event_from_entry(entry([65, 66, 255]), COMMENTS) is None
    assert agent.event_from_entry({"__CURSOR": "x", "__REALTIME_TIMESTAMP": "1"}, COMMENTS) is None


def test_parse_keygen_output_maps_fingerprints_to_comments():
    assert COMMENTS == {
        "SHA256:EfqGKQMTw+nb+BML5rZY5l1jBvXSKm6zQ5kBz/KaFkY": "mael.namania@gmail.com",
        "SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls": "claude-audit@mac-namania",
        "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA": None,
    }


def test_authorized_keys_reload_only_when_the_file_changes(tmp_path):
    path = tmp_path / "authorized_keys"
    path.write_text("no-port-forwarding ssh-ed25519 AAAA claude-audit@mac-namania\n")
    calls = []

    class Result:
        stdout = KEYGEN_OUTPUT

    def run(cmd, **kwargs):
        calls.append(cmd)
        return Result()

    keys = agent.AuthorizedKeys(path, run=run)
    assert keys.comments()["SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls"] == "claude-audit@mac-namania"
    keys.comments()
    assert len(calls) == 1 and calls[0][:2] == ["ssh-keygen", "-lf"]
    import os
    os.utime(path, (1, 1))  # a different mtime: the file changed
    keys.comments()
    assert len(calls) == 2


def test_missing_authorized_keys_gives_an_empty_map(tmp_path):
    assert agent.AuthorizedKeys(tmp_path / "absent").comments() == {}


def test_refusal_memory_reports_one_refusal_per_connection():
    now = [0.0]
    memory = agent.RefusalMemory(ttl_seconds=120.0, clock=lambda: now[0])
    assert memory.first_time("203.0.113.5", 51234) is True
    assert memory.first_time("203.0.113.5", 51234) is False
    assert memory.first_time("203.0.113.5", 51235) is True
    now[0] = 121.0
    assert memory.first_time("203.0.113.5", 51234) is True  # forgotten after the ttl


class FakeOpener:
    """Scripted HTTP answers: an int is a status, an exception is raised."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer

        class Response:
            status = answer

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        if answer >= 400:
            raise urllib.error.HTTPError(request.full_url, answer, "err", {}, None)
        return Response()


def sample_event():
    return agent.event_from_entry(entry(ACCEPTED_LINE), COMMENTS)


def test_api_client_posts_json_with_the_device_key():
    opener = FakeOpener([201])
    client = agent.ApiClient("http://127.0.0.1:8080/api", "k3y", opener=opener)
    assert client.post(sample_event()) == 201
    request = opener.requests[0]
    assert request.full_url == "http://127.0.0.1:8080/api/ssh/events"
    assert request.get_header("X-device-key") == "k3y"
    body = json.loads(request.data)
    assert body["key_comment"] == "claude-audit@mac-namania" and body["port"] == 49513


def test_deliver_retries_with_backoff_without_advancing():
    opener = FakeOpener([OSError("refused"), 503, 502, 201])
    sleeps = []
    client = agent.ApiClient("http://x/api", "k", opener=opener)
    assert agent.deliver(client, sample_event(), sleep=sleeps.append) is True
    assert sleeps == [1, 2, 4]
    assert len(opener.requests) == 4


def test_duplicate_is_acknowledged_with_200():
    client = agent.ApiClient("http://x/api", "k", opener=FakeOpener([200]))
    assert agent.deliver(client, sample_event(), sleep=lambda s: None) is True


def test_a_422_drops_the_event_and_a_401_waits_a_minute():
    sleeps = []
    client = agent.ApiClient("http://x/api", "k", opener=FakeOpener([401, 422]))
    assert agent.deliver(client, sample_event(), sleep=sleeps.append) is True
    assert sleeps == [60]


def test_journal_command_resumes_from_the_cursor_or_replays_a_day():
    assert agent.journal_command("ssh", None, "-24h")[-2:] == ["--since", "-24h"]
    assert agent.journal_command("ssh", "s=1;i=7", "-24h")[-2:] == ["--after-cursor", "s=1;i=7"]
    assert agent.journal_command("ssh", None, "-24h")[:3] == ["journalctl", "-u", "ssh"]


def test_handle_entry_sends_one_refusal_per_connection_and_advances_the_cursor(tmp_path):
    opener = FakeOpener([201, 201])
    client = agent.ApiClient("http://x/api", "k", opener=opener)
    cursors = agent.CursorStore(tmp_path / "cursor")
    memory = agent.RefusalMemory(clock=lambda: 0.0)
    keys = agent.AuthorizedKeys(tmp_path / "absent")
    failed = entry("Failed password for root from 203.0.113.5 port 5 ssh2", cursor="c1")
    closed = entry("Connection closed by authenticating user root 203.0.113.5 port 5 [preauth]", cursor="c2")
    noise = entry("pam_unix(sshd:session): session closed for user sentinel-x", cursor="c3")
    assert agent.handle_entry(failed, keys, memory, client, cursors).reason == "bad_password"
    assert agent.handle_entry(closed, keys, memory, client, cursors) is None
    assert agent.handle_entry(noise, keys, memory, client, cursors) is None
    assert len(opener.requests) == 1
    assert cursors.read() == "c3"


def test_config_from_env_requires_the_device_key(tmp_path):
    with pytest.raises(SystemExit):
        agent.config_from_env({"HOME": str(tmp_path)})
    config = agent.config_from_env({"HOME": str(tmp_path), "DEVICE_API_KEY": "k"})
    assert config.api_url == "http://127.0.0.1:8080/api"
    assert config.authorized_keys == tmp_path / ".ssh" / "authorized_keys"
    assert config.state_dir == tmp_path / ".local" / "state" / "sentinel-x"
    assert (config.unit, config.first_run_since) == ("ssh", "-24h")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_ssh_log_agent.py -q 2>&1 | tail -3`
Expected: FAIL at import time (`FileNotFoundError` on the script path, or `AssertionError` from `spec is not None`).

- [ ] **Step 3: Write the agent**

`scripts/ssh-log-agent.py`:

```python
#!/usr/bin/env python3
"""Relay the Pi's SSH connections (accepted and refused) from journald to the SENTINEL-X API.

Runs on the host as a systemd user service (make ssh-log-install), standard library only:
  journalctl -u ssh -o json -f  →  parse the sshd lines  →  POST /api/ssh/events (X-Device-Key)
An accepted connection is enriched with the comment of its key in ~/.ssh/authorized_keys (the
mail). The journald cursor is kept on disk so nothing is lost while the API is down.
Design: docs/superpowers/specs/2026-10-08-ssh-access-log-design.md
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("ssh-log-agent")

ACCEPTED = re.compile(
    r"^Accepted (?P<method>[\w-]+)(?:/\S+)? for (?P<user>\S+) from (?P<ip>\S+) port (?P<port>\d+)"
    r" ssh2(?:: (?P<keytype>\S+) (?P<fp>SHA256:\S+))?$"
)
REFUSED = (
    (
        re.compile(
            r"^Connection closed by authenticating user (?P<user>\S+) (?P<ip>\S+) port (?P<port>\d+) \[preauth\]$"
        ),
        "key_rejected",
        None,
    ),
    (
        re.compile(
            r"^Connection closed by invalid user (?P<user>\S+) (?P<ip>\S+) port (?P<port>\d+) \[preauth\]$"
        ),
        "unknown_user",
        None,
    ),
    (
        re.compile(
            r"^Failed password for (?:invalid user )?(?P<user>\S+) from (?P<ip>\S+) port (?P<port>\d+) ssh2$"
        ),
        "bad_password",
        "password",
    ),
    (
        re.compile(
            r"^Disconnecting (?:invalid user |authenticating user )?(?P<user>\S+) (?P<ip>\S+) port (?P<port>\d+):"
            r" Too many authentication failures \[preauth\]$"
        ),
        "too_many_attempts",
        None,
    ),
)
KEYGEN_LINE = re.compile(r"^\d+ (?P<fp>SHA256:\S+) (?P<comment>.*) \((?P<type>[A-Z0-9-]+)\)$")
RETRY_DELAYS = (1, 2, 4, 8, 16, 30)
MAX_USERNAME = 64
MAX_IP = 45


@dataclass(frozen=True)
class Event:
    journal_id: str
    occurred_at: str
    outcome: str
    username: str
    ip: str
    port: int
    method: str | None = None
    key_fingerprint: str | None = None
    key_comment: str | None = None
    reason: str | None = None


def parse_message(message: str) -> dict | None:
    """The connection described by one sshd line, or None when the line is not one."""
    m = ACCEPTED.match(message)
    if m:
        return {
            "outcome": "accepted",
            "username": m["user"],
            "ip": m["ip"],
            "port": int(m["port"]),
            "method": m["method"],
            "key_fingerprint": m["fp"],
            "reason": None,
        }
    for pattern, reason, method in REFUSED:
        m = pattern.match(message)
        if m:
            return {
                "outcome": "refused",
                "username": m["user"],
                "ip": m["ip"],
                "port": int(m["port"]),
                "method": method,
                "key_fingerprint": None,
                "reason": reason,
            }
    return None


def _iso(micros: int) -> str:
    moment = datetime.fromtimestamp(micros / 1_000_000, tz=UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def event_from_entry(entry: dict, comments: dict[str, str | None]) -> Event | None:
    """One journald JSON entry → Event, or None (not a connection, or an unreadable message)."""
    message = entry.get("MESSAGE")
    if not isinstance(message, str):
        return None  # journalctl gives a byte array for non-UTF-8 text: a probe, not a login
    fields = parse_message(message)
    if fields is None:
        return None
    micros = int(entry.get("_SOURCE_REALTIME_TIMESTAMP") or entry["__REALTIME_TIMESTAMP"])
    fingerprint = fields["key_fingerprint"]
    return Event(
        journal_id=entry["__CURSOR"],
        occurred_at=_iso(micros),
        outcome=fields["outcome"],
        username=fields["username"][:MAX_USERNAME],
        ip=fields["ip"][:MAX_IP],
        port=fields["port"],
        method=fields["method"],
        key_fingerprint=fingerprint,
        key_comment=comments.get(fingerprint) if fingerprint else None,
        reason=fields["reason"],
    )


def parse_keygen_output(text: str) -> dict[str, str | None]:
    """`ssh-keygen -lf authorized_keys` → {fingerprint: comment}; "no comment" → None."""
    out: dict[str, str | None] = {}
    for line in text.splitlines():
        m = KEYGEN_LINE.match(line.strip())
        if m:
            comment = m["comment"].strip()
            out[m["fp"]] = None if comment in ("", "no comment") else comment
    return out


class AuthorizedKeys:
    """The fingerprint → comment map, reread when the file's mtime changes (make ssh-add)."""

    def __init__(self, path: Path, run: Callable[..., object] = subprocess.run) -> None:
        self._path = path
        self._run = run
        self._mtime: float | None = None
        self._comments: dict[str, str | None] = {}

    def comments(self) -> dict[str, str | None]:
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._mtime, self._comments = None, {}
            return {}
        if mtime != self._mtime:
            result = self._run(
                ["ssh-keygen", "-lf", str(self._path)], capture_output=True, text=True, check=False
            )
            self._comments = parse_keygen_output(getattr(result, "stdout", "") or "")
            self._mtime = mtime
        return self._comments


class RefusalMemory:
    """sshd can write two refusal lines for one connection: report the (ip, port) once."""

    def __init__(self, ttl_seconds: float = 120.0, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._seen: dict[tuple[str, int], float] = {}

    def first_time(self, ip: str, port: int) -> bool:
        now = self._clock()
        self._seen = {k: t for k, t in self._seen.items() if now - t < self._ttl}
        key = (ip, port)
        if key in self._seen:
            return False
        self._seen[key] = now
        return True


class ApiClient:
    def __init__(
        self,
        base_url: str,
        device_key: str,
        opener: Callable[..., object] = urllib.request.urlopen,
        timeout: float = 5.0,
    ) -> None:
        self._url = base_url.rstrip("/") + "/ssh/events"
        self._key = device_key
        self._opener = opener
        self._timeout = timeout

    def post(self, event: Event) -> int:
        """HTTP status of the API's answer; raises OSError when it cannot be reached."""
        request = urllib.request.Request(
            self._url,
            data=json.dumps(asdict(event)).encode(),
            headers={"Content-Type": "application/json", "X-Device-Key": self._key},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                return int(response.status)
        except urllib.error.HTTPError as exc:
            return exc.code


def deliver(client: ApiClient, event: Event, sleep: Callable[[float], None] = time.sleep) -> bool:
    """Send until the API has the event (201/200) or refuses it for good (422): then True, the
    cursor may advance. Network errors and 5xx retry with backoff; a wrong device key retries
    every minute (a configuration problem someone must fix)."""
    attempt = 0
    while True:
        try:
            status = client.post(event)
        except OSError as exc:
            status = None
            log.warning("API unreachable: %s", exc)
        if status in (200, 201):
            return True
        if status == 422:
            log.warning("event refused by the API (422), dropped: %s", asdict(event))
            return True
        if status in (401, 403):
            log.error("device key refused (HTTP %s): check DEVICE_API_KEY; retrying in 60 s", status)
            sleep(60)
            continue
        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
        attempt += 1
        if status is not None:
            log.warning("API answered %s, retrying in %s s", status, delay)
        sleep(delay)


class CursorStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> str | None:
        try:
            return self._path.read_text().strip() or None
        except FileNotFoundError:
            return None

    def write(self, cursor: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(cursor)
        os.replace(tmp, self._path)


def journal_command(unit: str, cursor: str | None, first_run_since: str) -> list[str]:
    cmd = ["journalctl", "-u", unit, "-o", "json", "-f", "--no-pager"]
    return cmd + (["--after-cursor", cursor] if cursor else ["--since", first_run_since])


def handle_entry(
    entry: dict, keys: AuthorizedKeys, memory: RefusalMemory, client: ApiClient, cursors: CursorStore
) -> Event | None:
    """Send the connection this entry describes, if any, then remember the cursor."""
    event = event_from_entry(entry, keys.comments())
    if event is not None and (event.outcome == "accepted" or memory.first_time(event.ip, event.port)):
        deliver(client, event)
    else:
        event = None
    cursor = entry.get("__CURSOR")
    if isinstance(cursor, str) and cursor:
        cursors.write(cursor)
    return event


@dataclass(frozen=True)
class Config:
    api_url: str
    device_key: str
    authorized_keys: Path
    state_dir: Path
    unit: str
    first_run_since: str


def config_from_env(env: dict[str, str] | os._Environ[str] = os.environ) -> Config:
    key = env.get("DEVICE_API_KEY", "").strip()
    if not key:
        raise SystemExit("DEVICE_API_KEY manquant (make ssh-log-install l'écrit dans ssh-log.env)")
    home = Path(env.get("HOME", str(Path.home())))
    return Config(
        api_url=env.get("SENTINEL_API_URL", "http://127.0.0.1:8080/api"),
        device_key=key,
        authorized_keys=Path(env.get("SENTINEL_AUTHORIZED_KEYS", home / ".ssh" / "authorized_keys")),
        state_dir=Path(env.get("SENTINEL_STATE_DIR", home / ".local" / "state" / "sentinel-x")),
        unit=env.get("SENTINEL_JOURNAL_UNIT", "ssh"),
        first_run_since=env.get("SENTINEL_FIRST_RUN_SINCE", "-24h"),
    )


def run(config: Config) -> None:
    keys = AuthorizedKeys(config.authorized_keys)
    cursors = CursorStore(config.state_dir / "ssh-log.cursor")
    memory = RefusalMemory()
    client = ApiClient(config.api_url, config.device_key)
    while True:
        cursor = cursors.read()
        cmd = journal_command(config.unit, cursor, config.first_run_since)
        log.info("following %s (%s)", config.unit, "from cursor" if cursor else "last 24 h")
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True) as proc:
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("unreadable journal line skipped")
                    continue
                event = handle_entry(entry, keys, memory, client, cursors)
                if event is not None:
                    log.info("%s %s from %s (%s)", event.outcome, event.username, event.ip,
                             event.key_comment or event.reason or event.method)
        log.warning("journalctl exited (%s); restarting in 5 s", proc.returncode)
        time.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    try:
        run(config_from_env())
    except KeyboardInterrupt:
        pass
```

Make it executable: `chmod +x scripts/ssh-log-agent.py`.

- [ ] **Step 4: Run the agent tests**

Run: `cd backend && uv run pytest tests/unit/test_ssh_log_agent.py -q 2>&1 | tail -3`
Expected: all passed (7 recognised lines, 9 ignored lines, 16 other tests).

- [ ] **Step 5: Lint the script and the test, commit**

```bash
cd backend && uv run ruff check --config pyproject.toml ../scripts/ssh-log-agent.py tests/unit/test_ssh_log_agent.py && uv run ruff format --config pyproject.toml ../scripts/ssh-log-agent.py tests/unit/test_ssh_log_agent.py && uv run pytest tests/unit -q | tail -1
cd .. && git add scripts/ssh-log-agent.py backend/tests/unit/test_ssh_log_agent.py && git commit -m "feat(ssh): host agent relaying sshd journal lines to /ssh/events

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Install script, Makefile and README

**Files:**
- Create: `scripts/ssh-log-install.sh`
- Modify: `Makefile` (header comment, `.PHONY`, two targets)
- Modify: `README.md` (section « Accès SSH au Pi », section « Alertes »)

**Interfaces:**
- Consumes: `scripts/ssh-log-agent.py` env variables `DEVICE_API_KEY`, `SENTINEL_API_URL` (Task 5).

- [ ] **Step 1: Write the install script**

`scripts/ssh-log-install.sh`:

```sh
#!/usr/bin/env sh
# Install the SSH access log agent on the Pi (make ssh-log-install): a systemd *user* service that
# relays sshd's journal lines to the API (scripts/ssh-log-agent.py). Needs backend/.env with
# DEVICE_API_KEY. Idempotent: run it again after pulling a new version of the agent.
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$REPO/backend/.env"
CONF_DIR="$HOME/.config/sentinel-x"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="sentinel-ssh-log"
API_URL="${SENTINEL_API_URL:-http://127.0.0.1:8080/api}"

[ -f "$ENV_FILE" ] || { echo "Introuvable : $ENV_FILE (copier backend/.env.example)." >&2; exit 1; }
KEY=$(sed -n 's/^DEVICE_API_KEY=//p' "$ENV_FILE" | head -1 | sed -e 's/^["'"'"']//' -e 's/["'"'"']$//')
[ -n "$KEY" ] || { echo "DEVICE_API_KEY est vide dans $ENV_FILE." >&2; exit 1; }
command -v journalctl >/dev/null || { echo "journalctl introuvable : cet agent lit journald." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 introuvable." >&2; exit 1; }

mkdir -p "$CONF_DIR" "$UNIT_DIR"
umask 077
printf 'DEVICE_API_KEY=%s\nSENTINEL_API_URL=%s\n' "$KEY" "$API_URL" > "$CONF_DIR/ssh-log.env"
umask 022

cat > "$UNIT_DIR/$UNIT.service" <<EOF
[Unit]
Description=SENTINEL-X: journal des connexions SSH vers l'API
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 $REPO/scripts/ssh-log-agent.py
EnvironmentFile=%h/.config/sentinel-x/ssh-log.env
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT.service"
systemctl --user restart "$UNIT.service"
# Without linger the user services (this one, and the rootless Docker) stop at the last logout.
loginctl enable-linger "$(id -un)" 2>/dev/null || echo "Avertissement : loginctl enable-linger a échoué ; lancer : sudo loginctl enable-linger $(id -un)" >&2

echo "Service $UNIT installé pour $(id -un)@$(hostname)."
systemctl --user --no-pager --lines=0 status "$UNIT.service" || true
echo "Logs : make ssh-log-logs    Retirer : systemctl --user disable --now $UNIT"
```

`chmod +x scripts/ssh-log-install.sh`. Check syntax: `sh -n scripts/ssh-log-install.sh`.

- [ ] **Step 2: Add the Makefile targets**

In `Makefile`: add to the header comment

```
#   make ssh-log-install  on the Pi: relay the SSH connections (accepted / refused) to the dashboard
#   make ssh-log-logs     follow that agent's logs
```

extend `.PHONY: dev deploy down logs ssh-add ssh-remove ssh-log-install ssh-log-logs`, and append:

```make
ssh-log-install:
	@sh scripts/ssh-log-install.sh

ssh-log-logs:
	journalctl --user -u sentinel-ssh-log -f
```

Check: `make -n ssh-log-install ssh-log-logs` prints both commands.

- [ ] **Step 3: Update the README**

In `README.md`, section « Accès SSH au Pi », append after the existing paragraph:

```markdown
**Journal des connexions.** `make ssh-log-install` (sur le Pi) installe un agent hors Docker
(`scripts/ssh-log-agent.py`, service utilisateur systemd `sentinel-ssh-log`, linger activé) qui
suit le journal de sshd et pousse chaque connexion à l'API (`POST /api/ssh/events`, en-tête
`X-Device-Key`) : acceptée, avec le **commentaire de la clé** (le mail) retrouvé dans
`~/.ssh/authorized_keys` ; refusée, avec l'utilisateur tenté, l'IP et la raison (clé non acceptée,
utilisateur inconnu, mot de passe refusé, trop de tentatives). La page `/ssh` « Accès SSH » les
liste en direct (`GET /api/ssh/events?outcome=all|accepted|refused&limit=…`, événement WebSocket
`ssh.event`). Un refus ouvre une alerte `ssh` par IP (`device_id` = `ip:…`, valeur = nombre de
tentatives), résolue après `SSH_ALERT_QUIET_MINUTES` (10) sans nouvelle tentative ; ajouter `ssh` à
`BUZZER_TRIGGERS` pour qu'elle fasse sonner le buzzer. Au premier démarrage l'agent rejoue les 24
dernières heures, puis reprend au curseur journald : rien n'est perdu pendant un `make deploy`.
`make ssh-log-logs` suit ses logs ; `systemctl --user disable --now sentinel-ssh-log` le retire.
```

In section « Alertes », after `GET /api/alerts/summary` → `{"open": n}`, add the sentence: « La métrique `ssh` (connexions SSH refusées, voir « Accès SSH au Pi ») suit le même cycle ; quand son compteur monte l'API émet `alert.updated`. »

- [ ] **Step 4: Commit**

```bash
sh -n scripts/ssh-log-install.sh && make -n ssh-log-install ssh-log-logs
git add scripts/ssh-log-install.sh Makefile README.md && git commit -m "feat(ops): make ssh-log-install / ssh-log-logs and README for the SSH access log

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Front — the `ssh` metric in the alerts feature, `alert.updated`, shared day groups

**Files:**
- Create: `frontend/src/lib/day-groups.ts`, `frontend/src/lib/day-groups.test.ts`
- Modify: `frontend/src/features/alerts/alerts-api.ts`, `alert-tile.tsx:47`, `alerts-page-content.tsx:32`, `metric-icon.tsx`, `siren-api.ts`, `use-alerts.ts`
- Modify: `frontend/src/index.css` (two `--metric-ssh` tokens)
- Test: `frontend/src/features/alerts/alerts-api.test.ts`, `use-alerts.test.tsx`

**Interfaces:**
- Produces: `Metric` includes `"ssh"`; `ipFromDevice(alert: Alert): string`; `attemptsLabel(n: number): string`; `lib/day-groups.ts`: `dayLabel(ms, nowMs)`, `groupByDay<T>(items: T[], nowMs: number, at: (item: T) => string): DayGroup<T>[]` with `DayGroup<T> = { label: string; items: T[] }`; `alerts-api.ts` keeps `groupByDay(alerts, nowMs)` → `{ label, alerts }[]` and re-exports `dayLabel`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/day-groups.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { dayLabel, groupByDay } from "./day-groups";

const NOW = Date.UTC(2026, 9, 8, 9, 0, 0);

describe("day groups", () => {
  it("labels today, yesterday and older days", () => {
    expect(dayLabel(NOW - 60_000, NOW)).toBe("Aujourd'hui");
    expect(dayLabel(NOW - 86_400_000, NOW)).toBe("Hier");
    expect(dayLabel(Date.UTC(2026, 9, 5, 12), NOW)).toMatch(/^lun\. 5 oct\.$/);
  });

  it("groups any items by the day of the given timestamp, keeping their order", () => {
    const items = [
      { id: "a", at: new Date(NOW - 60_000).toISOString() },
      { id: "b", at: new Date(NOW - 120_000).toISOString() },
      { id: "c", at: new Date(NOW - 86_400_000).toISOString() },
    ];
    const groups = groupByDay(items, NOW, (i) => i.at);
    expect(groups.map((g) => g.label)).toEqual(["Aujourd'hui", "Hier"]);
    expect(groups[0].items.map((i) => i.id)).toEqual(["a", "b"]);
  });
});
```

Append to `frontend/src/features/alerts/alerts-api.test.ts` (inside the describe), and add `ipFromDevice`, `attemptsLabel` to its import list:

```ts
  it("describes an ssh alert by its attempts and its ip", () => {
    const one = makeAlert({ metric: "ssh", device_id: "ip:203.0.113.5", threshold: 0, opened_value: 1, peak_value: 1 });
    const three = { ...one, peak_value: 3 };
    expect(describeAlert(one)).toBe("SSH : 1 tentative refusée depuis 203.0.113.5");
    expect(describeAlert(three)).toBe("SSH : 3 tentatives refusées depuis 203.0.113.5");
    expect(peakLabel(three)).toBe("3 tentatives");
    expect(boundLabel(three)).toBeNull();
    expect(excessLabel(three)).toBeNull();
    expect(ipFromDevice(makeAlert({ device_id: "ip:fe80::1" }))).toBe("fe80::1");
    expect(ipFromDevice(makeAlert({ device_id: "esp-interieur" }))).toBe("esp-interieur");
    expect(attemptsLabel(1)).toBe("1 tentative");
    expect(summarize([three], ALERTS_NOW_MS).topMetric).toBe("ssh");
  });
```

Append to `frontend/src/features/alerts/use-alerts.test.tsx` (inside the describe):

```ts
  it("replaces the alert on alert.updated without changing the count", async () => {
    const clients: { send(data: string): void }[] = [];
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        clients.push(client);
      }),
    );
    renderProbe();
    await screen.findByText("status:ready");
    await screen.findByText("count:0");
    await wait(50);
    const opened = makeAlert({ id: "ssh", metric: "ssh", device_id: "ip:203.0.113.5", peak_value: 1 });
    clients.forEach((c) => c.send(JSON.stringify({ type: "alert.opened", data: opened })));
    expect(await screen.findByText("open:1")).toBeInTheDocument();
    clients.forEach((c) =>
      c.send(JSON.stringify({ type: "alert.updated", data: { ...opened, peak_value: 2 } })),
    );
    await wait(50);
    expect(screen.getByText("total:2")).toBeInTheDocument();
    expect(screen.getByText("open:1")).toBeInTheDocument();
    expect(screen.getByText("count:1")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && pnpm exec vitest run src/lib/day-groups.test.ts src/features/alerts/alerts-api.test.ts src/features/alerts/use-alerts.test.tsx 2>&1 | tail -8`
Expected: `day-groups` fails to resolve the module; the alerts tests fail on the TS error / wrong text (« SSH ... »), `alert.updated` ignored (`open:1` holds but the updated data is not reflected — the test passes trivially on counts; its value is the type acceptance of `metric: "ssh"`, which fails typecheck). Run `pnpm typecheck 2>&1 | tail -3` too: Expected errors on `"ssh"` not assignable to `Metric`.

- [ ] **Step 3: Create the shared day groups**

`frontend/src/lib/day-groups.ts`:

```ts
const DAY_LABEL = new Intl.DateTimeFormat("fr-FR", {
  weekday: "short",
  day: "numeric",
  month: "short",
});

function localDay(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

/** « Aujourd'hui », « Hier », then « lun. 6 oct. » — for grouping a timeline by day. */
export function dayLabel(ms: number, nowMs: number): string {
  if (localDay(ms) === localDay(nowMs)) return "Aujourd'hui";
  if (localDay(ms) === localDay(nowMs - 86_400_000)) return "Hier";
  return DAY_LABEL.format(new Date(ms));
}

export type DayGroup<T> = { label: string; items: T[] };

/** Items grouped by the day of `at(item)`, in the order given (newest day first when sorted). */
export function groupByDay<T>(items: T[], nowMs: number, at: (item: T) => string): DayGroup<T>[] {
  const groups: DayGroup<T>[] = [];
  for (const item of items) {
    const label = dayLabel(Date.parse(at(item)), nowMs);
    const last = groups.at(-1);
    if (last && last.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }
  return groups;
}
```

- [ ] **Step 4: Teach the alerts feature the `ssh` metric**

`frontend/src/features/alerts/alerts-api.ts`:
- `export type Metric = "temperature" | "humidity" | "gas" | "ssh";`
- `METRIC_LABELS`: add `ssh: "SSH",`; `UNITS`: `ssh: "",`; `DIGITS`: `ssh: 0,`; `METRIC_COLORS`: `ssh: "var(--metric-ssh)",`; `summarize` counts: `{ temperature: 0, humidity: 0, gas: 0, ssh: 0 }`.
- add after `isOpen`:

```ts
/** The IP of an "ssh" alert's `device_id` (`ip:203.0.113.5` -> "203.0.113.5"). */
export function ipFromDevice(alert: Alert): string {
  return alert.device_id.startsWith("ip:") ? alert.device_id.slice("ip:".length) : alert.device_id;
}

/** « 1 tentative », « 3 tentatives » — an ssh alert's peak is a count. */
export function attemptsLabel(count: number): string {
  const n = Math.round(count);
  return `${n} ${n > 1 ? "tentatives" : "tentative"}`;
}
```

- `valueAgainstBound`: first line `if (alert.metric === "ssh") return \`${attemptsLabel(alert.peak_value)} ${Math.round(alert.peak_value) > 1 ? "refusées" : "refusée"} depuis ${ipFromDevice(alert)}\`;`
- `describeAlert`: after computing `label`, `if (alert.metric === "ssh") return \`${label} : ${valueAgainstBound(alert)}\`;`
- `peakLabel`: first line `if (alert.metric === "ssh") return attemptsLabel(alert.peak_value);`
- `boundLabel` and `excessLabel`: first line `if (alert.metric === "ssh") return null;`
- replace the local `DAY_LABEL`, `localDay`, `dayLabel`, `DayGroup`, `groupByDay` block with:

```ts
import { groupByDay as groupItemsByDay, dayLabel } from "@/lib/day-groups";

export { dayLabel };

export type DayGroup = { label: string; alerts: Alert[] };

/** Alerts grouped by the day they opened, newest day first; input order is kept inside a day. */
export function groupByDay(alerts: Alert[], nowMs: number): DayGroup[] {
  return groupItemsByDay(alerts, nowMs, (a) => a.opened_at).map((g) => ({
    label: g.label,
    alerts: g.items,
  }));
}
```

(put the import at the top of the file with the others).

`frontend/src/features/alerts/alert-tile.tsx` line 47: `<span className="text-muted-foreground text-sm">{alert.metric === "ssh" ? "tentatives de connexion refusées" : "alerte signalée par l'ESP"}</span>`.

`frontend/src/features/alerts/alerts-page-content.tsx` line 32: `const METRICS: Metric[] = ["temperature", "humidity", "gas", "ssh"];`

`frontend/src/features/alerts/metric-icon.tsx`: import `KeyRound` from lucide and add `ssh: KeyRound,` to `ICONS`.

`frontend/src/features/alerts/siren-api.ts`: add `ssh: "SSH",` to `REASONS`.

`frontend/src/features/alerts/use-alerts.ts`, in `onEvent`: `if ((type !== "alert.opened" && type !== "alert.resolved" && type !== "alert.updated") || !data) return;` and update the hook's doc comment to mention `alert.updated`.

`frontend/src/index.css`: after `--metric-gas: #0f8f6a;` add `--metric-ssh: #7c3aed;`; after `--metric-gas: #2aa87f;` (dark block) add `--metric-ssh: #a78bfa;`.

- [ ] **Step 5: Run the checks**

Run: `cd frontend && pnpm typecheck 2>&1 | tail -2 && pnpm exec vitest run src/lib src/features/alerts src/features/dashboard 2>&1 | tail -5`
Expected: typecheck clean; all tests pass.

- [ ] **Step 6: Lint, format and commit**

```bash
cd frontend && pnpm lint && pnpm exec prettier --write src/lib/day-groups.ts src/lib/day-groups.test.ts src/features/alerts && pnpm exec vitest run 2>&1 | grep -E "Test Files|Tests "
cd .. && git add frontend && git commit -m "feat(front): ssh alert metric, alert.updated and shared day grouping

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Front — `features/ssh` API helpers, hook, test fixtures and MSW handler

**Files:**
- Create: `frontend/src/features/ssh/ssh-api.ts`, `frontend/src/features/ssh/use-ssh-events.ts`, `frontend/src/test/ssh.ts`
- Modify: `frontend/src/test/server.ts` (handler `GET /api/ssh/events`)
- Test: `frontend/src/features/ssh/ssh-api.test.ts`, `frontend/src/features/ssh/use-ssh-events.test.tsx`

**Interfaces:**
- Consumes: `sinceLabel` from `@/features/alerts/alerts-api`; `useEventStream`, `useResyncKey`, `useAuth`.
- Produces: `SshEvent`, `Outcome`, `Reason`, `SSH_EVENTS_PATH`, `SSH_LIMIT`, `sshEventsPath(limit?)`, `REASON_LABELS`, `METHOD_LABELS`, `shortFingerprint(fp)`, `identityLabel(e)`, `describeEvent(e)`, `prepend(events, e)`, `summarizeSsh(events, nowMs)`; `useSshEvents(enabled?) → { status, events, connected }`; test helpers `SSH_NOW_MS`, `makeSshEvent(overrides)`, `sshEventsFixture()`.

- [ ] **Step 1: Write the fixtures and the failing tests**

`frontend/src/test/ssh.ts`:

```ts
import type { SshEvent } from "@/features/ssh/ssh-api";

export const SSH_NOW_MS = Date.UTC(2026, 9, 8, 9, 0, 0);

export function makeSshEvent(overrides: Partial<SshEvent> = {}): SshEvent {
  return {
    id: "ssh-1",
    journal_id: "s=1;i=1",
    occurred_at: new Date(SSH_NOW_MS - 4 * 60_000).toISOString(),
    outcome: "accepted",
    username: "sentinel-x",
    ip: "192.168.0.18",
    port: 49513,
    method: "publickey",
    key_fingerprint: "SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls",
    key_comment: "mael.namania@gmail.com",
    reason: null,
    ...overrides,
  };
}

/** Default API state in tests: one accepted connection, one refusal an hour earlier. */
export function sshEventsFixture(): SshEvent[] {
  return [
    makeSshEvent(),
    makeSshEvent({
      id: "ssh-refused",
      journal_id: "s=1;i=0",
      occurred_at: new Date(SSH_NOW_MS - 60 * 60_000).toISOString(),
      outcome: "refused",
      username: "root",
      ip: "203.0.113.5",
      port: 51234,
      method: null,
      key_fingerprint: null,
      key_comment: null,
      reason: "key_rejected",
    }),
  ];
}
```

In `frontend/src/test/server.ts`: import `{ sshEventsFixture } from "./ssh"` and add to `handlers`:

```ts
  http.get("/api/ssh/events", ({ request }) => {
    if (!isValidAccessToken(bearer(request))) return unauthenticated();
    const url = new URL(request.url);
    const outcome = url.searchParams.get("outcome") ?? "all";
    const limit = Number(url.searchParams.get("limit") ?? 100);
    return HttpResponse.json(
      sshEventsFixture()
        .filter((e) => outcome === "all" || e.outcome === outcome)
        .slice(0, limit),
    );
  }),
```

`frontend/src/features/ssh/ssh-api.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { makeSshEvent, SSH_NOW_MS, sshEventsFixture } from "@/test/ssh";
import { describeEvent, identityLabel, prepend, shortFingerprint, sshEventsPath, summarizeSsh } from "./ssh-api";

describe("ssh api helpers", () => {
  it("builds the list path with the limit", () => {
    expect(sshEventsPath()).toBe("/ssh/events?limit=500");
    expect(sshEventsPath(10)).toBe("/ssh/events?limit=10");
  });

  it("names who connected: key comment, else a short fingerprint, else the user", () => {
    expect(identityLabel(makeSshEvent())).toBe("mael.namania@gmail.com");
    expect(identityLabel(makeSshEvent({ key_comment: null }))).toBe("SHA256:Wqjh…9ls");
    expect(identityLabel(makeSshEvent({ key_comment: null, key_fingerprint: null }))).toBe("sentinel-x");
    expect(shortFingerprint("SHA256:abc")).toBe("SHA256:abc");
  });

  it("describes accepted and refused connections", () => {
    expect(describeEvent(makeSshEvent())).toBe("mael.namania@gmail.com depuis 192.168.0.18 · clé");
    expect(describeEvent(makeSshEvent({ method: "password" }))).toBe("mael.namania@gmail.com depuis 192.168.0.18 · mot de passe");
    expect(describeEvent(makeSshEvent({ method: null }))).toBe("mael.namania@gmail.com depuis 192.168.0.18");
    const refused = sshEventsFixture()[1];
    expect(describeEvent(refused)).toBe("root depuis 203.0.113.5 · clé non acceptée");
    expect(describeEvent({ ...refused, reason: "unknown_user" })).toBe("root depuis 203.0.113.5 · utilisateur inconnu");
    expect(describeEvent({ ...refused, reason: "bad_password" })).toBe("root depuis 203.0.113.5 · mot de passe refusé");
    expect(describeEvent({ ...refused, reason: "too_many_attempts" })).toBe("root depuis 203.0.113.5 · trop de tentatives");
  });

  it("prepends newest first, deduplicates by id and caps the list", () => {
    const list = sshEventsFixture();
    const newer = makeSshEvent({ id: "new", occurred_at: new Date(SSH_NOW_MS).toISOString() });
    expect(prepend(list, newer).map((e) => e.id)).toEqual(["new", "ssh-1", "ssh-refused"]);
    expect(prepend(list, { ...list[0], username: "x" }).map((e) => e.id)).toEqual(["ssh-1", "ssh-refused"]);
    const many = Array.from({ length: 500 }, (_, i) => makeSshEvent({ id: `e${i}` }));
    expect(prepend(many, newer)).toHaveLength(500);
    expect(prepend(many, newer)[0].id).toBe("new");
  });

  it("summarises the last 24 hours and the last accepted connection", () => {
    const old = makeSshEvent({ id: "old", occurred_at: new Date(SSH_NOW_MS - 30 * 3_600_000).toISOString() });
    const summary = summarizeSsh([...sshEventsFixture(), old], SSH_NOW_MS);
    expect(summary).toEqual({ accepted24h: 1, refused24h: 1, lastAccepted: sshEventsFixture()[0] });
    expect(summarizeSsh([], SSH_NOW_MS).lastAccepted).toBeNull();
  });
});
```

`frontend/src/features/ssh/use-ssh-events.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import { makeSshEvent } from "@/test/ssh";
import { useSshEvents } from "./use-ssh-events";

function Probe() {
  const { status, events } = useSshEvents();
  return (
    <div>
      <p>status:{status}</p>
      <p>ids:{events.map((e) => e.id).join(",")}</p>
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

describe("useSshEvents", () => {
  it("loads the list newest first", async () => {
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("ids:ssh-1,ssh-refused")).toBeInTheDocument();
  });

  it("prepends ssh.event events", async () => {
    const clients: { send(data: string): void }[] = [];
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        clients.push(client);
      }),
    );
    renderProbe();
    await screen.findByText("status:ready");
    await wait(50);
    clients.forEach((c) =>
      c.send(JSON.stringify({ type: "ssh.event", data: makeSshEvent({ id: "live", occurred_at: "2026-10-08T09:00:00Z" }) })),
    );
    expect(await screen.findByText("ids:live,ssh-1,ssh-refused")).toBeInTheDocument();
  });

  it("keeps an event that arrives before the list", async () => {
    server.use(
      http.get("/api/ssh/events", async () => {
        await wait(100);
        return HttpResponse.json([makeSshEvent()]);
      }),
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(JSON.stringify({ type: "ssh.event", data: makeSshEvent({ id: "early", occurred_at: "2026-10-08T09:00:00Z" }) }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("ids:early,ssh-1")).toBeInTheDocument();
  });

  it("recovers from a failed list request on the first event", async () => {
    server.use(
      http.get("/api/ssh/events", () => HttpResponse.error()),
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(JSON.stringify({ type: "ssh.event", data: makeSshEvent({ id: "late" }) }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("ids:late")).toBeInTheDocument();
  });

  it("reports an error when the list fails and nothing arrives", async () => {
    server.use(http.get("/api/ssh/events", () => HttpResponse.error()));
    renderProbe();
    expect(await screen.findByText("status:error")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && pnpm exec vitest run src/features/ssh 2>&1 | tail -6`
Expected: both files fail to resolve `./ssh-api` / `./use-ssh-events`.

- [ ] **Step 3: Write `ssh-api.ts`**

```ts
export type Outcome = "accepted" | "refused";
export type Reason = "key_rejected" | "unknown_user" | "bad_password" | "too_many_attempts";

export type SshEvent = {
  id: string;
  journal_id: string;
  occurred_at: string;
  outcome: Outcome;
  username: string;
  ip: string;
  port: number;
  method: string | null;
  key_fingerprint: string | null;
  key_comment: string | null;
  reason: Reason | null;
};

export const SSH_EVENTS_PATH = "/ssh/events";
/** The API's maximum; the page says so when the history is longer. */
export const SSH_LIMIT = 500;

export function sshEventsPath(limit = SSH_LIMIT): string {
  return `${SSH_EVENTS_PATH}?limit=${limit}`;
}

export const REASON_LABELS: Record<Reason, string> = {
  key_rejected: "clé non acceptée",
  unknown_user: "utilisateur inconnu",
  bad_password: "mot de passe refusé",
  too_many_attempts: "trop de tentatives",
};

export const METHOD_LABELS: Record<string, string> = {
  publickey: "clé",
  password: "mot de passe",
  "keyboard-interactive": "interactif",
};

/** « SHA256:Wqjh…9ls » — enough to tell two keys apart on one line. */
export function shortFingerprint(fingerprint: string): string {
  return fingerprint.length > 16
    ? `${fingerprint.slice(0, 11)}…${fingerprint.slice(-3)}`
    : fingerprint;
}

/** Who connected: the key's comment (the mail), else its fingerprint, else the system user. */
export function identityLabel(event: SshEvent): string {
  if (event.key_comment) return event.key_comment;
  if (event.key_fingerprint) return shortFingerprint(event.key_fingerprint);
  return event.username;
}

/** « mael@… depuis 192.168.0.18 · clé » / « root depuis 203.0.113.5 · clé non acceptée ». */
export function describeEvent(event: SshEvent): string {
  if (event.outcome === "refused") {
    const reason = event.reason ? REASON_LABELS[event.reason] : "refusée";
    return `${event.username} depuis ${event.ip} · ${reason}`;
  }
  const method = event.method ? ` · ${METHOD_LABELS[event.method] ?? event.method}` : "";
  return `${identityLabel(event)} depuis ${event.ip}${method}`;
}

/** Add or replace the event with the same id; newest first, capped at SSH_LIMIT. */
export function prepend(events: SshEvent[], event: SshEvent): SshEvent[] {
  const others = events.filter((e) => e.id !== event.id);
  return [...others, event]
    .sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at))
    .slice(0, SSH_LIMIT);
}

export type SshSummary = { accepted24h: number; refused24h: number; lastAccepted: SshEvent | null };

export function summarizeSsh(events: SshEvent[], nowMs: number): SshSummary {
  let accepted24h = 0;
  let refused24h = 0;
  for (const e of events) {
    if (nowMs - Date.parse(e.occurred_at) > 86_400_000) continue;
    if (e.outcome === "accepted") accepted24h += 1;
    else refused24h += 1;
  }
  return {
    accepted24h,
    refused24h,
    lastAccepted: events.find((e) => e.outcome === "accepted") ?? null,
  };
}
```

- [ ] **Step 4: Write `use-ssh-events.ts`**

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { useEventStream } from "@/features/realtime/use-event-stream";
import { useResyncKey } from "@/features/realtime/use-resync-key";
import { prepend, sshEventsPath, type SshEvent } from "./ssh-api";

type Status = "loading" | "ready" | "error";

/** The SSH connection log, newest first, kept live by `ssh.event` events. */
export function useSshEvents(enabled = true) {
  const { authFetch } = useAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [events, setEvents] = useState<SshEvent[]>([]);
  // Events that arrive before the list response; merged once it lands.
  const pending = useRef<SshEvent[]>([]);
  const loaded = useRef(false);
  // Set when the list request failed; the first live event then rebuilds the state.
  const failed = useRef(false);

  const onEvent = useCallback((type: string, data: unknown) => {
    if (type !== "ssh.event" || !data) return;
    const event = data as SshEvent;
    if (!loaded.current && !failed.current) {
      pending.current = prepend(pending.current, event);
      return;
    }
    if (failed.current) {
      failed.current = false;
      loaded.current = true;
      const seeded = prepend(pending.current, event);
      pending.current = [];
      setEvents((current) => seeded.reduce((acc, e) => prepend(acc, e), current));
      setStatus("ready");
      return;
    }
    setEvents((current) => prepend(current, event));
  }, []);
  const { connected } = useEventStream(enabled, onEvent);
  // Events emitted while the socket was down are lost: reload the list after each reconnect.
  const resyncKey = useResyncKey(connected);

  useEffect(() => {
    let cancelled = false;
    loaded.current = false;
    failed.current = false;
    authFetch<SshEvent[]>(sshEventsPath())
      .then((list) => {
        if (cancelled) return;
        const sorted = [...list].sort(
          (a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at),
        );
        const merged = pending.current.reduce((acc, e) => prepend(acc, e), sorted);
        pending.current = [];
        loaded.current = true;
        setEvents(merged);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        failed.current = true;
        setStatus((current) => (current === "ready" ? current : "error"));
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, resyncKey]);

  return { status, events, connected };
}
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && pnpm typecheck 2>&1 | tail -2 && pnpm exec vitest run src/features/ssh 2>&1 | tail -5`
Expected: typecheck clean, `Tests 10 passed`.

- [ ] **Step 6: Lint, format and commit**

```bash
cd frontend && pnpm lint && pnpm exec prettier --write src/features/ssh src/test/ssh.ts src/test/server.ts && pnpm exec vitest run 2>&1 | grep -E "Test Files|Tests "
cd .. && git add frontend && git commit -m "feat(front): ssh events api helpers and live hook

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Front — the « Accès SSH » page, route and sidebar entry

**Files:**
- Create: `frontend/src/features/ssh/ssh-event-row.tsx`, `frontend/src/features/ssh/ssh-page-content.tsx`, `frontend/src/pages/ssh.tsx`
- Modify: `frontend/src/app/router.tsx`, `frontend/src/components/app-sidebar.tsx`
- Test: `frontend/src/features/ssh/ssh-page-content.test.tsx`, `frontend/src/app/router.test.tsx`, `frontend/src/components/app-sidebar.test.tsx`

**Interfaces:**
- Consumes: Task 8 helpers and hook; `groupByDay` from `@/lib/day-groups`; `sinceLabel` from `@/features/alerts/alerts-api`; `useNow`; shadcn `Card`, `Input`, `Skeleton`, `ToggleGroup`.
- Produces: route `/ssh`, page title « Accès SSH · sentinel-x », sidebar link « Accès SSH ».

- [ ] **Step 1: Write the failing tests**

`frontend/src/features/ssh/ssh-page-content.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { server, VALID_REFRESH } from "@/test/server";
import { makeSshEvent, SSH_NOW_MS } from "@/test/ssh";
import { SshPageContent } from "./ssh-page-content";

function renderPage() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes([{ path: "/ssh", element: <SshPageContent nowMs={SSH_NOW_MS} /> }], "/ssh");
}

describe("SshPageContent", () => {
  it("summarises and lists the connections grouped by day", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Accès SSH" })).toBeInTheDocument();
    expect(screen.getByText("Connexions 24 h").nextElementSibling).toHaveTextContent("1");
    expect(screen.getByText("Refus 24 h").nextElementSibling).toHaveTextContent("1");
    expect(screen.getByText("Dernière acceptée").nextElementSibling).toHaveTextContent("mael.namania@gmail.com");
    expect(screen.getByText("il y a 4 min")).toBeInTheDocument();
    const today = within(screen.getByRole("list", { name: "Connexions, Aujourd'hui" }));
    const rows = today.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("mael.namania@gmail.com depuis 192.168.0.18 · clé");
    expect(rows[0]).toHaveTextContent("Acceptée");
    expect(rows[1]).toHaveTextContent("root depuis 203.0.113.5 · clé non acceptée");
    expect(rows[1]).toHaveTextContent("Refusée");
  });

  it("filters by outcome and by text", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Accès SSH" });
    await user.click(screen.getByRole("radio", { name: "Refusées" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText(/root depuis/)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Toutes" }));
    await user.type(screen.getByRole("searchbox", { name: "Rechercher" }), "MAEL");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText(/mael\.namania/)).toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox", { name: "Rechercher" }));
    await user.type(screen.getByRole("searchbox", { name: "Rechercher" }), "203.0.113");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    await user.click(screen.getByRole("radio", { name: "Acceptées" }));
    expect(screen.getByText("Aucune connexion")).toBeInTheDocument();
  });

  it("shows the loading, error and truncated states", async () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    server.use(http.get("/api/ssh/events", () => HttpResponse.error()));
    renderRoutes([{ path: "/ssh", element: <SshPageContent nowMs={SSH_NOW_MS} /> }], "/ssh");
    expect(screen.getByRole("status", { name: "Chargement des connexions" })).toBeInTheDocument();
    expect(await screen.findByText("Journal SSH indisponible.")).toBeInTheDocument();
    server.use(
      http.get("/api/ssh/events", ({ request }) => {
        expect(Number(new URL(request.url).searchParams.get("limit"))).toBe(500);
        return HttpResponse.json(
          Array.from({ length: 500 }, (_, i) =>
            makeSshEvent({ id: `e${i}`, occurred_at: new Date(SSH_NOW_MS - (i + 1) * 60_000).toISOString() }),
          ),
        );
      }),
    );
    renderRoutes([{ path: "/ssh", element: <SshPageContent nowMs={SSH_NOW_MS} /> }], "/ssh");
    expect(
      await screen.findByText("Seules les 500 connexions les plus récentes sont affichées."),
    ).toBeInTheDocument();
  });
});
```

Append to `frontend/src/app/router.test.tsx` (inside the describe):

```ts
  it("serves the SSH access log on /ssh", async () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    renderRoutes(routes, "/ssh");
    expect(await screen.findByRole("heading", { name: "Accès SSH" })).toBeInTheDocument();
    expect(document.title).toBe("Accès SSH · sentinel-x");
  });
```

In `frontend/src/components/app-sidebar.test.tsx`, first test: add `expect(nav.getByRole("link", { name: "Accès SSH" })).toHaveAttribute("href", "/ssh");` and rename it `"links to the dashboard, the camera, the server, the alerts and the SSH log"`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && pnpm exec vitest run src/features/ssh/ssh-page-content.test.tsx src/app/router.test.tsx src/components/app-sidebar.test.tsx 2>&1 | tail -8`
Expected: the page test fails to resolve `./ssh-page-content`; the router test finds no « Accès SSH » heading (404 page); the sidebar test finds no « Accès SSH » link.

- [ ] **Step 3: Write the row**

`frontend/src/features/ssh/ssh-event-row.tsx`:

```tsx
import { Check, X } from "lucide-react";
import { formatTime } from "@/lib/format-number";
import { cn } from "@/lib/utils";
import { describeEvent, type SshEvent } from "./ssh-api";

/** One connection on one line: outcome mark, who/where/how, system user, time. */
export function SshEventRow({ event }: { event: SshEvent }) {
  const ok = event.outcome === "accepted";
  return (
    <li className="flex items-center gap-3 py-2 text-sm">
      <span
        aria-hidden="true"
        className={cn(
          "grid size-7 shrink-0 place-items-center rounded-full",
          ok
            ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
            : "bg-destructive/15 text-destructive",
        )}
      >
        {ok ? <Check className="size-4" /> : <X className="size-4" />}
      </span>
      <span className="min-w-0 flex-1 truncate">{describeEvent(event)}</span>
      <span
        className="text-muted-foreground hidden w-24 shrink-0 truncate text-xs sm:inline"
        title={`port ${event.port}`}
      >
        {event.username}
      </span>
      <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
        {formatTime(Date.parse(event.occurred_at))}
      </span>
      <span className="sr-only">{ok ? "Acceptée" : "Refusée"}</span>
    </li>
  );
}
```

- [ ] **Step 4: Write the page content**

`frontend/src/features/ssh/ssh-page-content.tsx`:

```tsx
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { sinceLabel } from "@/features/alerts/alerts-api";
import { groupByDay } from "@/lib/day-groups";
import { useNow } from "@/lib/use-now";
import { identityLabel, SSH_LIMIT, summarizeSsh, type Outcome, type SshEvent } from "./ssh-api";
import { SshEventRow } from "./ssh-event-row";
import { useSshEvents } from "./use-ssh-events";

type OutcomeFilter = "all" | Outcome;

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{label}</p>
        <p className="mt-1 truncate text-2xl font-semibold tabular-nums">{value}</p>
        {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function matches(event: SshEvent, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return [event.ip, event.username, event.key_comment ?? "", event.key_fingerprint ?? ""].some(
    (v) => v.toLowerCase().includes(q),
  );
}

/** The /ssh page: a summary, outcome and text filters, the connections as a day timeline. */
export function SshPageContent({ nowMs }: { nowMs?: number }) {
  const { status, events } = useSshEvents();
  const tick = useNow();
  const now = nowMs ?? tick;
  const [outcome, setOutcome] = useState<OutcomeFilter>("all");
  const [query, setQuery] = useState("");

  const filtered = events
    .filter((e) => outcome === "all" || e.outcome === outcome)
    .filter((e) => matches(e, query.trim()));
  const summary = summarizeSsh(events, now);

  return (
    <section aria-labelledby="ssh-title" className="space-y-5">
      <h1 id="ssh-title" className="text-2xl font-semibold">
        Accès SSH
      </h1>

      {status === "ready" && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat label="Connexions 24 h" value={String(summary.accepted24h)} hint="acceptées" />
          <Stat
            label="Refus 24 h"
            value={String(summary.refused24h)}
            hint={summary.refused24h > 0 ? "ouvrent une alerte SSH" : "aucune tentative refusée"}
          />
          <Stat
            label="Dernière acceptée"
            value={summary.lastAccepted ? identityLabel(summary.lastAccepted) : "–"}
            hint={
              summary.lastAccepted
                ? `il y a ${sinceLabel(now - Date.parse(summary.lastAccepted.occurred_at))}`
                : undefined
            }
          />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-4">
        <ToggleGroup
          type="single"
          value={outcome}
          onValueChange={(v) => v && setOutcome(v as OutcomeFilter)}
          aria-label="Résultat"
          variant="outline"
        >
          <ToggleGroupItem value="all">Toutes</ToggleGroupItem>
          <ToggleGroupItem value="accepted">Acceptées</ToggleGroupItem>
          <ToggleGroupItem value="refused">Refusées</ToggleGroupItem>
        </ToggleGroup>
        <Input
          type="search"
          aria-label="Rechercher"
          placeholder="IP, mail, utilisateur"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-56"
        />
      </div>

      {status === "loading" && (
        <Skeleton role="status" aria-label="Chargement des connexions" className="h-40 w-full" />
      )}
      {status === "error" && <p className="text-destructive">Journal SSH indisponible.</p>}
      {status === "ready" && filtered.length === 0 && (
        <p className="text-muted-foreground">Aucune connexion</p>
      )}
      {status === "ready" && events.length >= SSH_LIMIT && (
        <p className="text-muted-foreground text-sm">
          Seules les {SSH_LIMIT} connexions les plus récentes sont affichées.
        </p>
      )}

      {filtered.length > 0 && (
        <section aria-labelledby="ssh-history-title" className="space-y-4">
          <h2 id="ssh-history-title" className="text-sm font-medium">
            Historique
          </h2>
          {groupByDay(filtered, now, (e) => e.occurred_at).map((group) => (
            <div key={group.label} className="relative pl-5">
              <span
                aria-hidden="true"
                className="bg-border absolute top-2 bottom-2 left-1.5 w-px"
              />
              <h3 className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
                <span
                  aria-hidden="true"
                  className="bg-muted-foreground/60 absolute top-1.5 left-0 size-3 rounded-full ring-4 ring-[var(--background)]"
                />
                {group.label}
              </h3>
              <ul className="divide-y" aria-label={`Connexions, ${group.label}`}>
                {group.items.map((e) => (
                  <SshEventRow key={e.id} event={e} />
                ))}
              </ul>
            </div>
          ))}
        </section>
      )}
    </section>
  );
}
```

Note: `sinceLabel(4 min)` gives « 4 min », so the hint reads « il y a 4 min » (the test expects exactly that).

- [ ] **Step 5: Page, route and sidebar**

`frontend/src/pages/ssh.tsx`:

```tsx
import { SshPageContent } from "@/features/ssh/ssh-page-content";
import { useDocumentTitle } from "@/lib/use-document-title";

export function SshPage() {
  useDocumentTitle("Accès SSH · sentinel-x");
  return (
    <div className="flex flex-1 flex-col p-6">
      <SshPageContent />
    </div>
  );
}
```

`frontend/src/app/router.tsx`: import `{ SshPage } from "@/pages/ssh"` and add `{ path: "/ssh", element: <SshPage /> },` after the `/alertes` route.

`frontend/src/components/app-sidebar.tsx`: add `KeyRound` to the lucide import and `{ to: "/ssh", label: "Accès SSH", icon: KeyRound, end: false },` after the Alertes item in `NAV_ITEMS`.

- [ ] **Step 6: Run the checks**

Run: `cd frontend && pnpm typecheck 2>&1 | tail -2 && pnpm exec vitest run 2>&1 | grep -E "Test Files|Tests |FAIL"`
Expected: typecheck clean, every test file passed.

- [ ] **Step 7: Lint, format, build and commit**

```bash
cd frontend && pnpm lint && pnpm exec prettier --write src/features/ssh src/pages/ssh.tsx src/app src/components && pnpm build >/dev/null; echo "build exit: $?"
cd .. && git add frontend && git commit -m "feat(front): Accès SSH page with live connection log in the sidebar

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: End-to-end check on the Pi (read-only on the host, deploy decided by the user)

**Files:** none. This task only verifies; the agent install (`make ssh-log-install`) runs on the Pi and is the user's command to run after `develop` reaches `main` and `make deploy`.

- [ ] **Step 1: Syntax-check the agent with the Pi's Python**

Run from the Mac: `scp -P 26655 -i ~/.ssh/sentinel-x-audit_ed25519 -o IdentitiesOnly=yes scripts/ssh-log-agent.py sentinel-x@192.168.0.70:/tmp/ssh-log-agent.py && ssh -p 26655 -i ~/.ssh/sentinel-x-audit_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes sentinel-x@192.168.0.70 'python3 -m py_compile /tmp/ssh-log-agent.py && echo compiled && DEVICE_API_KEY=x python3 -c "import importlib.util as u; s=u.spec_from_file_location(\"a\",\"/tmp/ssh-log-agent.py\"); m=u.module_from_spec(s); s.loader.exec_module(m); import json,subprocess; out=subprocess.run([\"journalctl\",\"-u\",\"ssh\",\"-o\",\"json\",\"-n\",\"40\",\"--no-pager\"],capture_output=True,text=True).stdout; keys=m.AuthorizedKeys(m.Path.home()/\".ssh\"/\"authorized_keys\").comments(); ev=[m.event_from_entry(json.loads(l),keys) for l in out.splitlines()]; print([ (e.outcome,e.username,e.ip,e.key_comment) for e in ev if e][-5:])"; rm /tmp/ssh-log-agent.py'`
Expected: `compiled`, then the last five parsed connections from the real journal, e.g. `('accepted', 'sentinel-x', '192.168.0.18', 'claude-audit@mac-namania')`.

- [ ] **Step 2: Record the result in the final message**

No commit. Report what the Pi parsed, and remind the user that the agent goes live with `make ssh-log-install` once `develop` is merged into `main` and deployed (migration 0006 runs with the API).
