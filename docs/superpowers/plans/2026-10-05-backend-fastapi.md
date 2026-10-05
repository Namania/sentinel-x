# Backend FastAPI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `backend/` FastAPI service with clean architecture, JWT email/password auth, an authenticated WebSocket channel, and the compose stack (Postgres + API + nginx) that runs it on the Raspberry Pi.

**Architecture:** Four layers with a strict inward dependency rule: `domain` (pure Python entities and repository interface) ← `application` (use cases and ports) ← `infrastructure` (SQLAlchemy, Argon2, PyJWT, in-memory WS hub, settings) and `presentation` (FastAPI routers, WS endpoint, composition root). Use cases receive their ports by constructor; all wiring lives in `presentation/dependencies.py` and `presentation/main.py`.

**Tech Stack:** Python 3.12, uv, FastAPI, uvicorn[standard], SQLAlchemy 2 async + asyncpg, Alembic, pydantic-settings, pwdlib[argon2], PyJWT, pytest + pytest-asyncio + httpx, ruff, PostgreSQL 16, nginx, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-05-backend-fastapi-design.md`

## Global Constraints

- Python `>=3.12`; project managed with `uv`; all commands below run from `backend/` unless stated otherwise.
- `src/app/domain` and `src/app/application` must never import `fastapi`, `sqlalchemy`, `jwt`, `pydantic`, `starlette` or `pwdlib`. Verified by `grep -rE "fastapi|sqlalchemy|jwt|pydantic|starlette|pwdlib" src/app/domain src/app/application` returning nothing.
- Emails are normalised with `.strip().lower()` before any lookup or storage.
- Password minimum length: 8 characters (validated at the presentation layer).
- Access token: JWT HS256, claims `sub`, `type="access"`, `exp` (default 900 s). Refresh token: same with `type="refresh"` (default 604800 s).
- Error mapping: `EmailAlreadyUsed` → 409, `InvalidCredentials` → 401, `UserNotFound` → 404, missing/invalid bearer → 401.
- WebSocket at `/ws?token=<access_token>`; invalid or missing token → close code 1008 before `accept()`.
- nginx listens on container port 80, published on host `8080`; `/api/` is proxied to `api:8000/` with the `/api` prefix stripped; `/ws` is proxied with Upgrade headers.
- Docker on the Pi is rootless: never publish a host port below 1024.
- Commit after every task with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. Email case/whitespace: a user registered as `" Foo@Bar.com "` must be able to log in as `foo@bar.com`, and registering `foo@bar.com` again must be rejected with 409. → Tests added in Task 4 (unit) and Task 8 (integration).
2. Wrong token type: an access token POSTed to `/auth/refresh` must be refused with 401, and a refresh token used as bearer on `/users/me` must be refused with 401. → Tests in Task 4 (unit) and Task 8 (integration).
3. Expired token: an expired access token on `/users/me` must give 401, not 500. → Test in Task 5 (unit, `decode` raises `InvalidToken` on expiry) and Task 8 (integration).
4. WebSocket without or with a bad token must be closed with 1008 and never reach `accept()`. → Tests in Task 9.
5. A malformed (non-JSON) WebSocket message must produce an error frame and keep the connection open. → Test in Task 9.

---

### Task 1: Project scaffold and health endpoint

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.gitignore`
- Create: `backend/src/app/__init__.py` (empty)
- Create: `backend/src/app/presentation/__init__.py` (empty)
- Create: `backend/src/app/presentation/http/__init__.py` (empty)
- Create: `backend/src/app/presentation/http/health.py`
- Create: `backend/src/app/presentation/main.py`
- Create: `backend/tests/__init__.py` (empty)
- Create: `backend/tests/integration/__init__.py` (empty)
- Test: `backend/tests/integration/test_health.py`

**Interfaces:**
- Produces: `app.presentation.main.create_app(settings=None) -> FastAPI` (settings parameter is added in Task 8; for now it takes no argument). Later tasks add routers and `app.state` entries inside `create_app`.

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "sentinel-backend"
version = "0.1.0"
description = "sentinel-x backend"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "pydantic-settings>=2.4",
    "pydantic[email]>=2.8",
    "pwdlib[argon2]>=0.2",
    "pyjwt>=2.9",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "websockets>=13",
    "ruff>=0.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/app"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Create `backend/.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.env
```

- [ ] **Step 3: Create empty package files**

Run (from `backend/`):
```bash
mkdir -p src/app/presentation/http tests/integration
touch src/app/__init__.py src/app/presentation/__init__.py src/app/presentation/http/__init__.py tests/__init__.py tests/integration/__init__.py
```

- [ ] **Step 4: Install dependencies and generate the lock file**

Run: `uv sync`
Expected: `.venv` created, `uv.lock` written, no errors.

- [ ] **Step 5: Write the failing test**

`backend/tests/integration/test_health.py`:
```python
from fastapi.testclient import TestClient

from app.presentation.main import create_app


def test_health_returns_ok():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.presentation.main'`

- [ ] **Step 7: Write the health router**

`backend/src/app/presentation/http/health.py`:
```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 8: Write the app factory**

`backend/src/app/presentation/main.py`:
```python
from fastapi import FastAPI

from app.presentation.http import health


def create_app() -> FastAPI:
    app = FastAPI(title="sentinel-x")
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 9: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_health.py -v`
Expected: PASS

- [ ] **Step 10: Lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no errors (run `uv run ruff format .` if formatting differs).

- [ ] **Step 11: Commit**

```bash
git add backend
git commit -m "feat(backend): scaffold FastAPI project with health endpoint

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Domain layer

**Files:**
- Create: `backend/src/app/domain/__init__.py` (empty)
- Create: `backend/src/app/domain/user.py`
- Create: `backend/src/app/domain/errors.py`
- Create: `backend/src/app/domain/repositories.py`
- Create: `backend/tests/unit/__init__.py` (empty)
- Test: `backend/tests/unit/test_user.py`

**Interfaces:**
- Produces:
  - `app.domain.user.User` — frozen dataclass `(id: UUID, email: str, password_hash: str, created_at: datetime)` with `User.create(email: str, password_hash: str) -> User`.
  - `app.domain.errors.DomainError`, `EmailAlreadyUsed`, `InvalidCredentials`, `UserNotFound` (all subclass `DomainError`, which subclasses `Exception`).
  - `app.domain.repositories.UserRepository` — abstract: `async get_by_id(user_id: UUID) -> User | None`, `async get_by_email(email: str) -> User | None`, `async add(user: User) -> None`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_user.py`:
```python
from datetime import UTC
from uuid import UUID

from app.domain.user import User


def test_create_generates_id_and_timestamp():
    user = User.create(email="alice@example.com", password_hash="hash")
    assert isinstance(user.id, UUID)
    assert user.created_at.tzinfo is UTC
    assert user.password_hash == "hash"


def test_create_normalises_email():
    user = User.create(email="  Alice@Example.COM ", password_hash="hash")
    assert user.email == "alice@example.com"


def test_two_users_have_distinct_ids():
    a = User.create(email="a@example.com", password_hash="h")
    b = User.create(email="b@example.com", password_hash="h")
    assert a.id != b.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `mkdir -p tests/unit && touch tests/unit/__init__.py && uv run pytest tests/unit/test_user.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain'`

- [ ] **Step 3: Write the domain files**

`backend/src/app/domain/__init__.py`: empty.

`backend/src/app/domain/user.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4


def normalise_email(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    email: str
    password_hash: str
    created_at: datetime

    @classmethod
    def create(cls, email: str, password_hash: str) -> User:
        return cls(
            id=uuid4(),
            email=normalise_email(email),
            password_hash=password_hash,
            created_at=datetime.now(UTC),
        )
```

`backend/src/app/domain/errors.py`:
```python
class DomainError(Exception):
    """Base class for business rule violations."""


class EmailAlreadyUsed(DomainError):
    pass


class InvalidCredentials(DomainError):
    pass


class UserNotFound(DomainError):
    pass
```

`backend/src/app/domain/repositories.py`:
```python
from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.user import User


class UserRepository(ABC):
    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def add(self, user: User) -> None: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_user.py -v`
Expected: 3 PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add backend
git commit -m "feat(backend): add domain layer with User entity and repository interface

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Application ports, DTOs, test fakes and RegisterUser

**Files:**
- Create: `backend/src/app/application/__init__.py` (empty)
- Create: `backend/src/app/application/ports/__init__.py` (empty)
- Create: `backend/src/app/application/ports/password_hasher.py`
- Create: `backend/src/app/application/ports/token_service.py`
- Create: `backend/src/app/application/ports/unit_of_work.py`
- Create: `backend/src/app/application/ports/event_broadcaster.py`
- Create: `backend/src/app/application/auth/__init__.py` (empty)
- Create: `backend/src/app/application/auth/dtos.py`
- Create: `backend/src/app/application/auth/register.py`
- Create: `backend/tests/unit/fakes.py`
- Test: `backend/tests/unit/test_register_user.py`

**Interfaces:**
- Consumes: `User`, `UserRepository`, `EmailAlreadyUsed` from Task 2.
- Produces:
  - `PasswordHasher` Protocol: `hash(password: str) -> str`, `verify(password: str, password_hash: str) -> bool`.
  - `TokenPayload(user_id: UUID, type: str)`, `InvalidToken(Exception)`, `TokenService` Protocol: `issue_access(user_id: UUID) -> str`, `issue_refresh(user_id: UUID) -> str`, `decode(token: str) -> TokenPayload` (raises `InvalidToken`).
  - `UnitOfWork` ABC: attribute `users: UserRepository`, async context manager, `async commit()`, `async rollback()`.
  - `Event = dict[str, Any]`, `EventBroadcaster` Protocol: `async broadcast(event: Event) -> None`, `async send_to_user(user_id: UUID, event: Event) -> None`.
  - DTOs: `RegisterInput(email, password)`, `LoginInput(email, password)`, `TokenPair(access_token, refresh_token)`, `UserOutput(id, email, created_at)` with `UserOutput.from_user(user)`.
  - `RegisterUser(uow: UnitOfWork, hasher: PasswordHasher).execute(data: RegisterInput) -> UserOutput`.
  - Test fakes in `tests/unit/fakes.py`: `InMemoryUserRepository`, `InMemoryUnitOfWork`, `FakePasswordHasher`, `FakeTokenService`, `RecordingBroadcaster`.

- [ ] **Step 1: Write the ports**

`backend/src/app/application/__init__.py`, `backend/src/app/application/ports/__init__.py`, `backend/src/app/application/auth/__init__.py`: empty.

`backend/src/app/application/ports/password_hasher.py`:
```python
from typing import Protocol


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, password_hash: str) -> bool: ...
```

`backend/src/app/application/ports/token_service.py`:
```python
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

TokenType = Literal["access", "refresh"]


class InvalidToken(Exception):
    """Raised when a token cannot be decoded or has expired."""


@dataclass(frozen=True, slots=True)
class TokenPayload:
    user_id: UUID
    type: str


class TokenService(Protocol):
    def issue_access(self, user_id: UUID) -> str: ...

    def issue_refresh(self, user_id: UUID) -> str: ...

    def decode(self, token: str) -> TokenPayload: ...
```

`backend/src/app/application/ports/unit_of_work.py`:
```python
from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType

from app.domain.repositories import UserRepository


class UnitOfWork(ABC):
    users: UserRepository

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
```

`backend/src/app/application/ports/event_broadcaster.py`:
```python
from typing import Any, Protocol
from uuid import UUID

Event = dict[str, Any]


class EventBroadcaster(Protocol):
    async def broadcast(self, event: Event) -> None: ...

    async def send_to_user(self, user_id: UUID, event: Event) -> None: ...
```

- [ ] **Step 2: Write the DTOs**

`backend/src/app/application/auth/dtos.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.user import User


@dataclass(frozen=True, slots=True)
class RegisterInput:
    email: str
    password: str


@dataclass(frozen=True, slots=True)
class LoginInput:
    email: str
    password: str


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class UserOutput:
    id: UUID
    email: str
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> UserOutput:
        return cls(id=user.id, email=user.email, created_at=user.created_at)
```

- [ ] **Step 3: Write the test fakes**

`backend/tests/unit/fakes.py`:
```python
from __future__ import annotations

from uuid import UUID

from app.application.ports.event_broadcaster import Event
from app.application.ports.token_service import InvalidToken, TokenPayload
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.repositories import UserRepository
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


class InMemoryUnitOfWork(UnitOfWork):
    def __init__(self) -> None:
        self.users = InMemoryUserRepository()
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
```

- [ ] **Step 4: Write the failing tests for RegisterUser**

`backend/tests/unit/test_register_user.py`:
```python
import pytest

from app.application.auth.dtos import RegisterInput
from app.application.auth.register import RegisterUser
from app.domain.errors import EmailAlreadyUsed
from tests.unit.fakes import FakePasswordHasher, InMemoryUnitOfWork


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    return InMemoryUnitOfWork()


@pytest.fixture
def use_case(uow: InMemoryUnitOfWork) -> RegisterUser:
    return RegisterUser(uow=uow, hasher=FakePasswordHasher())


async def test_register_stores_hashed_password_and_commits(uow, use_case):
    output = await use_case.execute(RegisterInput(email="alice@example.com", password="secret123"))

    stored = await uow.users.get_by_id(output.id)
    assert stored is not None
    assert stored.password_hash == "hashed:secret123"
    assert output.email == "alice@example.com"
    assert uow.committed is True


async def test_register_normalises_email(uow, use_case):
    output = await use_case.execute(RegisterInput(email=" Alice@Example.COM ", password="secret123"))
    assert output.email == "alice@example.com"
    assert await uow.users.get_by_email("alice@example.com") is not None


async def test_register_rejects_duplicate_email_case_insensitive(use_case):
    await use_case.execute(RegisterInput(email="alice@example.com", password="secret123"))
    with pytest.raises(EmailAlreadyUsed):
        await use_case.execute(RegisterInput(email="ALICE@example.com", password="other123"))
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_register_user.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.auth.register'`

- [ ] **Step 6: Write RegisterUser**

`backend/src/app/application/auth/register.py`:
```python
from app.application.auth.dtos import RegisterInput, UserOutput
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.errors import EmailAlreadyUsed
from app.domain.user import User, normalise_email


class RegisterUser:
    def __init__(self, uow: UnitOfWork, hasher: PasswordHasher) -> None:
        self._uow = uow
        self._hasher = hasher

    async def execute(self, data: RegisterInput) -> UserOutput:
        email = normalise_email(data.email)
        async with self._uow as uow:
            if await uow.users.get_by_email(email) is not None:
                raise EmailAlreadyUsed(email)
            user = User.create(email=email, password_hash=self._hasher.hash(data.password))
            await uow.users.add(user)
            await uow.commit()
        return UserOutput.from_user(user)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/unit -v`
Expected: all PASS

- [ ] **Step 8: Check the dependency rule**

Run: `grep -rE "fastapi|sqlalchemy|jwt|pydantic|starlette|pwdlib" src/app/domain src/app/application || echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add backend
git commit -m "feat(backend): add application ports and RegisterUser use case

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: LoginUser, RefreshTokens and GetCurrentUser use cases

**Files:**
- Create: `backend/src/app/application/auth/login.py`
- Create: `backend/src/app/application/auth/refresh.py`
- Create: `backend/src/app/application/users/__init__.py` (empty)
- Create: `backend/src/app/application/users/get_me.py`
- Test: `backend/tests/unit/test_login_user.py`
- Test: `backend/tests/unit/test_refresh_tokens.py`
- Test: `backend/tests/unit/test_get_current_user.py`

**Interfaces:**
- Consumes: ports, DTOs, fakes and `RegisterUser` from Task 3; `InvalidCredentials`, `UserNotFound` from Task 2.
- Produces:
  - `LoginUser(uow, hasher, tokens: TokenService, broadcaster: EventBroadcaster).execute(data: LoginInput) -> TokenPair`; on success broadcasts `{"type": "user.logged_in", "user_id": "<uuid str>"}`.
  - `RefreshTokens(uow, tokens).execute(refresh_token: str) -> TokenPair`.
  - `GetCurrentUser(uow).execute(user_id: UUID) -> UserOutput`.

- [ ] **Step 1: Write the failing tests for LoginUser**

`backend/tests/unit/test_login_user.py`:
```python
import pytest

from app.application.auth.dtos import LoginInput, RegisterInput
from app.application.auth.login import LoginUser
from app.application.auth.register import RegisterUser
from app.domain.errors import InvalidCredentials
from tests.unit.fakes import (
    FakePasswordHasher,
    FakeTokenService,
    InMemoryUnitOfWork,
    RecordingBroadcaster,
)


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    return InMemoryUnitOfWork()


@pytest.fixture
def broadcaster() -> RecordingBroadcaster:
    return RecordingBroadcaster()


@pytest.fixture
def login(uow, broadcaster) -> LoginUser:
    return LoginUser(
        uow=uow, hasher=FakePasswordHasher(), tokens=FakeTokenService(), broadcaster=broadcaster
    )


@pytest.fixture
async def registered_user(uow):
    register = RegisterUser(uow=uow, hasher=FakePasswordHasher())
    return await register.execute(RegisterInput(email=" Alice@Example.com ", password="secret123"))


async def test_login_returns_token_pair(login, registered_user):
    pair = await login.execute(LoginInput(email="alice@example.com", password="secret123"))
    assert pair.access_token == f"access:{registered_user.id}"
    assert pair.refresh_token == f"refresh:{registered_user.id}"


async def test_login_is_case_insensitive_on_email(login, registered_user):
    pair = await login.execute(LoginInput(email="ALICE@EXAMPLE.COM", password="secret123"))
    assert pair.access_token == f"access:{registered_user.id}"


async def test_login_broadcasts_logged_in_event(login, broadcaster, registered_user):
    await login.execute(LoginInput(email="alice@example.com", password="secret123"))
    assert broadcaster.broadcasts == [
        {"type": "user.logged_in", "user_id": str(registered_user.id)}
    ]


async def test_login_rejects_wrong_password(login, broadcaster, registered_user):
    with pytest.raises(InvalidCredentials):
        await login.execute(LoginInput(email="alice@example.com", password="wrong1234"))
    assert broadcaster.broadcasts == []


async def test_login_rejects_unknown_email(login):
    with pytest.raises(InvalidCredentials):
        await login.execute(LoginInput(email="nobody@example.com", password="secret123"))
```

- [ ] **Step 2: Write the failing tests for RefreshTokens**

`backend/tests/unit/test_refresh_tokens.py`:
```python
from uuid import uuid4

import pytest

from app.application.auth.dtos import RegisterInput
from app.application.auth.refresh import RefreshTokens
from app.application.auth.register import RegisterUser
from app.domain.errors import InvalidCredentials
from tests.unit.fakes import FakePasswordHasher, FakeTokenService, InMemoryUnitOfWork


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    return InMemoryUnitOfWork()


@pytest.fixture
def refresh(uow) -> RefreshTokens:
    return RefreshTokens(uow=uow, tokens=FakeTokenService())


@pytest.fixture
async def user(uow):
    register = RegisterUser(uow=uow, hasher=FakePasswordHasher())
    return await register.execute(RegisterInput(email="alice@example.com", password="secret123"))


async def test_refresh_issues_new_pair(refresh, user):
    pair = await refresh.execute(f"refresh:{user.id}")
    assert pair.access_token == f"access:{user.id}"
    assert pair.refresh_token == f"refresh:{user.id}"


async def test_refresh_rejects_access_token(refresh, user):
    with pytest.raises(InvalidCredentials):
        await refresh.execute(f"access:{user.id}")


async def test_refresh_rejects_garbage_token(refresh):
    with pytest.raises(InvalidCredentials):
        await refresh.execute("not-a-token")


async def test_refresh_rejects_unknown_user(refresh):
    with pytest.raises(InvalidCredentials):
        await refresh.execute(f"refresh:{uuid4()}")
```

- [ ] **Step 3: Write the failing tests for GetCurrentUser**

`backend/tests/unit/test_get_current_user.py`:
```python
from uuid import uuid4

import pytest

from app.application.auth.dtos import RegisterInput
from app.application.auth.register import RegisterUser
from app.application.users.get_me import GetCurrentUser
from app.domain.errors import UserNotFound
from tests.unit.fakes import FakePasswordHasher, InMemoryUnitOfWork


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    return InMemoryUnitOfWork()


async def test_get_me_returns_user(uow):
    register = RegisterUser(uow=uow, hasher=FakePasswordHasher())
    created = await register.execute(RegisterInput(email="alice@example.com", password="secret123"))

    output = await GetCurrentUser(uow=uow).execute(created.id)

    assert output.id == created.id
    assert output.email == "alice@example.com"


async def test_get_me_raises_for_unknown_id(uow):
    with pytest.raises(UserNotFound):
        await GetCurrentUser(uow=uow).execute(uuid4())
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/unit -v`
Expected: the three new files FAIL with `ModuleNotFoundError`; earlier tests still PASS.

- [ ] **Step 5: Write LoginUser**

`backend/src/app/application/auth/login.py`:
```python
from app.application.auth.dtos import LoginInput, TokenPair
from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.token_service import TokenService
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.errors import InvalidCredentials
from app.domain.user import normalise_email


class LoginUser:
    def __init__(
        self,
        uow: UnitOfWork,
        hasher: PasswordHasher,
        tokens: TokenService,
        broadcaster: EventBroadcaster,
    ) -> None:
        self._uow = uow
        self._hasher = hasher
        self._tokens = tokens
        self._broadcaster = broadcaster

    async def execute(self, data: LoginInput) -> TokenPair:
        email = normalise_email(data.email)
        async with self._uow as uow:
            user = await uow.users.get_by_email(email)
        if user is None or not self._hasher.verify(data.password, user.password_hash):
            raise InvalidCredentials()
        pair = TokenPair(
            access_token=self._tokens.issue_access(user.id),
            refresh_token=self._tokens.issue_refresh(user.id),
        )
        await self._broadcaster.broadcast({"type": "user.logged_in", "user_id": str(user.id)})
        return pair
```

- [ ] **Step 6: Write RefreshTokens**

`backend/src/app/application/auth/refresh.py`:
```python
from app.application.auth.dtos import TokenPair
from app.application.ports.token_service import InvalidToken, TokenService
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.errors import InvalidCredentials


class RefreshTokens:
    def __init__(self, uow: UnitOfWork, tokens: TokenService) -> None:
        self._uow = uow
        self._tokens = tokens

    async def execute(self, refresh_token: str) -> TokenPair:
        try:
            payload = self._tokens.decode(refresh_token)
        except InvalidToken as exc:
            raise InvalidCredentials() from exc
        if payload.type != "refresh":
            raise InvalidCredentials()
        async with self._uow as uow:
            user = await uow.users.get_by_id(payload.user_id)
        if user is None:
            raise InvalidCredentials()
        return TokenPair(
            access_token=self._tokens.issue_access(user.id),
            refresh_token=self._tokens.issue_refresh(user.id),
        )
```

- [ ] **Step 7: Write GetCurrentUser**

`backend/src/app/application/users/__init__.py`: empty.

`backend/src/app/application/users/get_me.py`:
```python
from uuid import UUID

from app.application.auth.dtos import UserOutput
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.errors import UserNotFound


class GetCurrentUser:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID) -> UserOutput:
        async with self._uow as uow:
            user = await uow.users.get_by_id(user_id)
        if user is None:
            raise UserNotFound(str(user_id))
        return UserOutput.from_user(user)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/unit -v`
Expected: all PASS

- [ ] **Step 9: Check the dependency rule, lint and commit**

```bash
grep -rE "fastapi|sqlalchemy|jwt|pydantic|starlette|pwdlib" src/app/domain src/app/application || echo CLEAN
uv run ruff check . && uv run ruff format .
git add backend
git commit -m "feat(backend): add login, refresh and get-current-user use cases

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Settings, Argon2 hasher and JWT token service

**Files:**
- Create: `backend/src/app/infrastructure/__init__.py` (empty)
- Create: `backend/src/app/infrastructure/config.py`
- Create: `backend/src/app/infrastructure/security/__init__.py` (empty)
- Create: `backend/src/app/infrastructure/security/argon2_hasher.py`
- Create: `backend/src/app/infrastructure/security/jwt_token_service.py`
- Create: `backend/.env.example`
- Test: `backend/tests/unit/test_argon2_hasher.py`
- Test: `backend/tests/unit/test_jwt_token_service.py`

**Interfaces:**
- Consumes: `TokenPayload`, `InvalidToken` from Task 3.
- Produces:
  - `Settings` (pydantic-settings) with fields `database_url: str`, `jwt_secret: str`, `jwt_access_ttl_seconds: int = 900`, `jwt_refresh_ttl_seconds: int = 604800`; reads `.env` and environment.
  - `Argon2PasswordHasher()` implementing `PasswordHasher`.
  - `JwtTokenService(secret: str, access_ttl_seconds: int, refresh_ttl_seconds: int, algorithm: str = "HS256")` implementing `TokenService`.

- [ ] **Step 1: Write the failing hasher test**

`backend/tests/unit/test_argon2_hasher.py`:
```python
from app.infrastructure.security.argon2_hasher import Argon2PasswordHasher


def test_hash_is_not_plaintext_and_verifies():
    hasher = Argon2PasswordHasher()
    digest = hasher.hash("secret123")
    assert digest != "secret123"
    assert digest.startswith("$argon2")
    assert hasher.verify("secret123", digest) is True


def test_verify_rejects_wrong_password():
    hasher = Argon2PasswordHasher()
    digest = hasher.hash("secret123")
    assert hasher.verify("wrong", digest) is False
```

- [ ] **Step 2: Write the failing JWT tests**

`backend/tests/unit/test_jwt_token_service.py`:
```python
from uuid import uuid4

import pytest

from app.application.ports.token_service import InvalidToken
from app.infrastructure.security.jwt_token_service import JwtTokenService


@pytest.fixture
def service() -> JwtTokenService:
    return JwtTokenService(secret="test-secret", access_ttl_seconds=900, refresh_ttl_seconds=3600)


def test_access_token_round_trip(service):
    user_id = uuid4()
    payload = service.decode(service.issue_access(user_id))
    assert payload.user_id == user_id
    assert payload.type == "access"


def test_refresh_token_round_trip(service):
    user_id = uuid4()
    payload = service.decode(service.issue_refresh(user_id))
    assert payload.user_id == user_id
    assert payload.type == "refresh"


def test_decode_rejects_wrong_secret(service):
    other = JwtTokenService(secret="other", access_ttl_seconds=900, refresh_ttl_seconds=3600)
    token = other.issue_access(uuid4())
    with pytest.raises(InvalidToken):
        service.decode(token)


def test_decode_rejects_expired_token():
    expired = JwtTokenService(secret="test-secret", access_ttl_seconds=-10, refresh_ttl_seconds=-10)
    token = expired.issue_access(uuid4())
    with pytest.raises(InvalidToken):
        expired.decode(token)


def test_decode_rejects_garbage(service):
    with pytest.raises(InvalidToken):
        service.decode("not.a.jwt")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_argon2_hasher.py tests/unit/test_jwt_token_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure'`

- [ ] **Step 4: Write settings**

`backend/src/app/infrastructure/__init__.py`, `backend/src/app/infrastructure/security/__init__.py`: empty.

`backend/src/app/infrastructure/config.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel"
    jwt_secret: str = "change-me"
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 604800
```

`backend/.env.example`:
```
# Copy to backend/.env. Docker Compose reads it for the api service.
# For local runs outside Docker, replace the host "db" by "localhost".
DATABASE_URL=postgresql+asyncpg://sentinel:sentinel@db:5432/sentinel
JWT_SECRET=change-me
JWT_ACCESS_TTL_SECONDS=900
JWT_REFRESH_TTL_SECONDS=604800
```

- [ ] **Step 5: Write the Argon2 hasher**

`backend/src/app/infrastructure/security/argon2_hasher.py`:
```python
from pwdlib import PasswordHash


class Argon2PasswordHasher:
    def __init__(self) -> None:
        self._hasher = PasswordHash.recommended()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        return self._hasher.verify(password, password_hash)
```

- [ ] **Step 6: Write the JWT token service**

`backend/src/app/infrastructure/security/jwt_token_service.py`:
```python
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from app.application.ports.token_service import InvalidToken, TokenPayload


class JwtTokenService:
    def __init__(
        self,
        secret: str,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
        algorithm: str = "HS256",
    ) -> None:
        self._secret = secret
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds
        self._algorithm = algorithm

    def issue_access(self, user_id: UUID) -> str:
        return self._issue(user_id, "access", self._access_ttl)

    def issue_refresh(self, user_id: UUID) -> str:
        return self._issue(user_id, "refresh", self._refresh_ttl)

    def decode(self, token: str) -> TokenPayload:
        try:
            claims = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.PyJWTError as exc:
            raise InvalidToken() from exc
        try:
            return TokenPayload(user_id=UUID(claims["sub"]), type=claims["type"])
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidToken() from exc

    def _issue(self, user_id: UUID, token_type: str, ttl_seconds: int) -> str:
        now = datetime.now(UTC)
        claims = {
            "sub": str(user_id),
            "type": token_type,
            "iat": now,
            "exp": now + timedelta(seconds=ttl_seconds),
        }
        return jwt.encode(claims, self._secret, algorithm=self._algorithm)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/unit -v`
Expected: all PASS

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add backend
git commit -m "feat(backend): add settings, Argon2 hasher and JWT token service

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Postgres persistence, unit of work and Alembic migration

**Files:**
- Modify: `compose.yml` (root) — add the `db` service
- Create: `docker/postgres/init-test-db.sql`
- Create: `backend/src/app/infrastructure/db/__init__.py` (empty)
- Create: `backend/src/app/infrastructure/db/models.py`
- Create: `backend/src/app/infrastructure/db/engine.py`
- Create: `backend/src/app/infrastructure/db/repositories.py`
- Create: `backend/src/app/infrastructure/db/unit_of_work.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_create_users.py`
- Create: `backend/tests/integration/conftest.py`
- Test: `backend/tests/integration/test_user_repository.py`

**Interfaces:**
- Consumes: `User`, `UserRepository` (Task 2), `UnitOfWork` (Task 3), `Settings` (Task 5).
- Produces:
  - `app.infrastructure.db.models.Base`, `UserModel` (table `users`: `id UUID PK`, `email VARCHAR(320) UNIQUE`, `password_hash VARCHAR(255)`, `created_at TIMESTAMPTZ`).
  - `create_engine(url: str) -> AsyncEngine`, `create_session_factory(engine) -> async_sessionmaker[AsyncSession]`.
  - `SqlAlchemyUserRepository(session: AsyncSession)` implementing `UserRepository`.
  - `SqlAlchemyUnitOfWork(session_factory)` implementing `UnitOfWork`; opens a fresh session on each `async with`.
  - Test fixtures in `tests/integration/conftest.py`: `TEST_DATABASE_URL`, `session_factory`, autouse `clean_db`.

- [ ] **Step 1: Add the `db` service to the root compose file**

Replace `compose.yml` at the repository root with:
```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: sentinel
      POSTGRES_PASSWORD: sentinel
      POSTGRES_DB: sentinel
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/postgres/init-test-db.sql:/docker-entrypoint-initdb.d/init-test-db.sql:ro
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sentinel -d sentinel"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped

  web:
    image: nginx:alpine
    container_name: web
    ports:
      - "8080:80"
    restart: unless-stopped

volumes:
  pgdata:
```

`docker/postgres/init-test-db.sql`:
```sql
CREATE DATABASE sentinel_test;
```

Run (from repo root): `docker compose up -d db && docker compose ps`
Expected: `db` reaches status `healthy` within ~15 s. If the volume already existed before this step, run `docker compose down -v` first so the init script executes.

- [ ] **Step 2: Write the failing repository tests**

`backend/tests/integration/conftest.py`:
```python
import asyncio
import os
import threading
from collections.abc import Callable, Coroutine, Iterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.infrastructure.db.models import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel_test"
)


def _run_isolated(coro_factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Run a coroutine on a fresh loop in a worker thread so the test loop is left untouched."""
    errors: list[BaseException] = []

    def target() -> None:
        try:
            asyncio.run(coro_factory())
        except BaseException as exc:  # noqa: BLE001 - re-raised in the main thread
            errors.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]


async def _reset_schema() -> None:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    _run_isolated(_reset_schema)
    yield


@pytest.fixture
async def session_factory():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
```

`backend/tests/integration/test_user_repository.py`:
```python
from uuid import uuid4

from app.domain.user import User
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


async def test_add_then_get_by_id_and_email(session_factory):
    uow = SqlAlchemyUnitOfWork(session_factory)
    user = User.create(email="alice@example.com", password_hash="hash")

    async with uow as tx:
        await tx.users.add(user)
        await tx.commit()

    async with uow as tx:
        by_id = await tx.users.get_by_id(user.id)
        by_email = await tx.users.get_by_email("alice@example.com")

    assert by_id == user
    assert by_email == user


async def test_get_unknown_returns_none(session_factory):
    uow = SqlAlchemyUnitOfWork(session_factory)
    async with uow as tx:
        assert await tx.users.get_by_id(uuid4()) is None
        assert await tx.users.get_by_email("nobody@example.com") is None


async def test_uncommitted_add_is_rolled_back(session_factory):
    uow = SqlAlchemyUnitOfWork(session_factory)
    user = User.create(email="bob@example.com", password_hash="hash")

    async with uow as tx:
        await tx.users.add(user)
        # no commit

    async with uow as tx:
        assert await tx.users.get_by_email("bob@example.com") is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_user_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.db'`

- [ ] **Step 4: Write the models and engine**

`backend/src/app/infrastructure/db/__init__.py`: empty.

`backend/src/app/infrastructure/db/models.py`:
```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

`backend/src/app/infrastructure/db/engine.py`:
```python
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 5: Write the repository and unit of work**

`backend/src/app/infrastructure/db/repositories.py`:
```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.repositories import UserRepository
from app.domain.user import User
from app.infrastructure.db.models import UserModel


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
```

`backend/src/app/infrastructure/db/unit_of_work.py`:
```python
from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.unit_of_work import UnitOfWork
from app.infrastructure.db.repositories import SqlAlchemyUserRepository


class SqlAlchemyUnitOfWork(UnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        self.users = SqlAlchemyUserRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        try:
            await self.rollback()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None
        await self._session.rollback()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_user_repository.py -v`
Expected: 3 PASS

- [ ] **Step 7: Set up Alembic**

`backend/alembic.ini`:
```ini
[alembic]
script_location = alembic
prepend_sys_path = src
file_template = %%(rev)s_%%(slug)s
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`backend/alembic/env.py`:
```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.infrastructure.config import Settings
from app.infrastructure.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", Settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

`backend/alembic/script.py.mako`:
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`backend/alembic/versions/0001_create_users.py`:
```python
"""create users

Revision ID: 0001
Revises:
Create Date: 2026-10-05

"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
```

- [ ] **Step 8: Run the migration against the dev database**

Run (from `backend/`): `DATABASE_URL=postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel uv run alembic upgrade head`
Expected: output ends with `Running upgrade  -> 0001, create users`.

Then verify there is no drift between the model and the migration:
`DATABASE_URL=postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel uv run alembic check`
Expected: `No new upgrade operations detected.`

- [ ] **Step 9: Run the full test suite, lint and commit**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format .
git add backend compose.yml docker
git commit -m "feat(backend): add Postgres repository, unit of work and initial migration

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
(Run `git add` and `git commit` from the repository root.)

---

### Task 7: In-memory WebSocket connection hub

**Files:**
- Create: `backend/src/app/infrastructure/realtime/__init__.py` (empty)
- Create: `backend/src/app/infrastructure/realtime/hub.py`
- Test: `backend/tests/unit/test_connection_hub.py`

**Interfaces:**
- Consumes: `Event`, `EventBroadcaster` from Task 3.
- Produces: `ConnectionHub()` implementing `EventBroadcaster`, plus `connect(user_id: UUID, connection: Connection) -> None`, `disconnect(user_id: UUID, connection: Connection) -> None`, property `connection_count: int`. `Connection` is a Protocol with `async send_json(data: Any) -> None` (Starlette's `WebSocket` satisfies it).

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_connection_hub.py`:
```python
from typing import Any
from uuid import uuid4

import pytest

from app.infrastructure.realtime.hub import ConnectionHub


class FakeConnection:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[Any] = []
        self.fail = fail

    async def send_json(self, data: Any) -> None:
        if self.fail:
            raise RuntimeError("connection closed")
        self.sent.append(data)


@pytest.fixture
def hub() -> ConnectionHub:
    return ConnectionHub()


async def test_broadcast_reaches_every_connection(hub):
    alice, bob = uuid4(), uuid4()
    a1, a2, b1 = FakeConnection(), FakeConnection(), FakeConnection()
    hub.connect(alice, a1)
    hub.connect(alice, a2)
    hub.connect(bob, b1)

    await hub.broadcast({"type": "hello"})

    assert a1.sent == a2.sent == b1.sent == [{"type": "hello"}]
    assert hub.connection_count == 3


async def test_send_to_user_targets_only_that_user(hub):
    alice, bob = uuid4(), uuid4()
    a1, b1 = FakeConnection(), FakeConnection()
    hub.connect(alice, a1)
    hub.connect(bob, b1)

    await hub.send_to_user(alice, {"type": "private"})

    assert a1.sent == [{"type": "private"}]
    assert b1.sent == []


async def test_disconnect_removes_connection(hub):
    alice = uuid4()
    a1 = FakeConnection()
    hub.connect(alice, a1)
    hub.disconnect(alice, a1)

    await hub.broadcast({"type": "hello"})

    assert a1.sent == []
    assert hub.connection_count == 0


async def test_failing_connection_does_not_break_broadcast(hub):
    alice = uuid4()
    dead, alive = FakeConnection(fail=True), FakeConnection()
    hub.connect(alice, dead)
    hub.connect(alice, alive)

    await hub.broadcast({"type": "hello"})

    assert alive.sent == [{"type": "hello"}]


def test_disconnect_unknown_is_noop(hub):
    hub.disconnect(uuid4(), FakeConnection())
    assert hub.connection_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_connection_hub.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.realtime'`

- [ ] **Step 3: Write the hub**

`backend/src/app/infrastructure/realtime/__init__.py`: empty.

`backend/src/app/infrastructure/realtime/hub.py`:
```python
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Protocol
from uuid import UUID

from app.application.ports.event_broadcaster import Event

logger = logging.getLogger(__name__)


class Connection(Protocol):
    async def send_json(self, data: Any) -> None: ...


class ConnectionHub:
    """Registry of live WebSocket connections, keyed by user. One instance per process."""

    def __init__(self) -> None:
        self._connections: dict[UUID, set[Connection]] = defaultdict(set)

    def connect(self, user_id: UUID, connection: Connection) -> None:
        self._connections[user_id].add(connection)

    def disconnect(self, user_id: UUID, connection: Connection) -> None:
        bucket = self._connections.get(user_id)
        if bucket is None:
            return
        bucket.discard(connection)
        if not bucket:
            del self._connections[user_id]

    @property
    def connection_count(self) -> int:
        return sum(len(bucket) for bucket in self._connections.values())

    async def broadcast(self, event: Event) -> None:
        for bucket in list(self._connections.values()):
            for connection in list(bucket):
                await self._safe_send(connection, event)

    async def send_to_user(self, user_id: UUID, event: Event) -> None:
        for connection in list(self._connections.get(user_id, ())):
            await self._safe_send(connection, event)

    async def _safe_send(self, connection: Connection, event: Event) -> None:
        try:
            await connection.send_json(event)
        except Exception:  # noqa: BLE001 - a dead socket must not break the others
            logger.debug("dropping event for a closed connection", exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_connection_hub.py -v`
Expected: 5 PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add backend
git commit -m "feat(backend): add in-memory WebSocket connection hub

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: HTTP layer — composition root, auth and users routes

**Files:**
- Create: `backend/src/app/presentation/dependencies.py`
- Create: `backend/src/app/presentation/http/errors.py`
- Create: `backend/src/app/presentation/http/auth.py`
- Create: `backend/src/app/presentation/http/users.py`
- Modify: `backend/src/app/presentation/main.py`
- Modify: `backend/tests/integration/conftest.py`
- Modify: `backend/tests/integration/test_health.py`
- Test: `backend/tests/integration/test_auth_http.py`

**Interfaces:**
- Consumes: use cases (Tasks 3–4), `Settings`, `Argon2PasswordHasher`, `JwtTokenService` (Task 5), `create_engine`, `create_session_factory`, `SqlAlchemyUnitOfWork` (Task 6), `ConnectionHub` (Task 7).
- Produces:
  - `create_app(settings: Settings | None = None) -> FastAPI`; sets `app.state.settings`, `app.state.session_factory`, `app.state.hub`.
  - Dependencies: `get_settings`, `get_uow`, `get_hasher`, `get_token_service`, `get_hub`, `get_current_user_id` (all take `HTTPConnection` so they also work in WebSocket routes).
  - Routes: `POST /auth/register` (201), `POST /auth/login` (200), `POST /auth/refresh` (200), `GET /users/me` (200).
  - Test fixtures: session-scoped `app` and `client` (Starlette `TestClient`), helper `register_and_login(client) -> dict` returning the token pair.

- [ ] **Step 1: Write the failing HTTP tests**

Update `backend/tests/integration/conftest.py` — add these imports and fixtures (keep the existing content):
```python
from fastapi.testclient import TestClient

from app.infrastructure.config import Settings
from app.presentation.main import create_app


@pytest.fixture(scope="session")
def app():
    return create_app(Settings(database_url=TEST_DATABASE_URL, jwt_secret="test-secret"))


@pytest.fixture(scope="session")
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def register_and_login(client: TestClient, email: str = "alice@example.com") -> dict:
    client.post("/auth/register", json={"email": email, "password": "secret123"})
    response = client.post("/auth/login", json={"email": email, "password": "secret123"})
    assert response.status_code == 200, response.text
    return response.json()
```

Update `backend/tests/integration/test_health.py` to use the shared client:
```python
def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

`backend/tests/integration/test_auth_http.py`:
```python
from uuid import uuid4

from app.infrastructure.security.jwt_token_service import JwtTokenService
from tests.integration.conftest import register_and_login


def test_register_returns_201_with_user(client):
    response = client.post(
        "/auth/register", json={"email": "Alice@Example.com", "password": "secret123"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert "id" in body and "created_at" in body
    assert "password" not in body and "password_hash" not in body


def test_register_duplicate_email_returns_409(client):
    client.post("/auth/register", json={"email": "alice@example.com", "password": "secret123"})
    response = client.post(
        "/auth/register", json={"email": " ALICE@example.com ", "password": "secret123"}
    )
    assert response.status_code == 409


def test_register_short_password_returns_422(client):
    response = client.post("/auth/register", json={"email": "alice@example.com", "password": "short"})
    assert response.status_code == 422


def test_register_invalid_email_returns_422(client):
    response = client.post("/auth/register", json={"email": "not-an-email", "password": "secret123"})
    assert response.status_code == 422


def test_login_returns_token_pair(client):
    tokens = register_and_login(client)
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"] and tokens["refresh_token"]


def test_login_wrong_password_returns_401(client):
    client.post("/auth/register", json={"email": "alice@example.com", "password": "secret123"})
    response = client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong1234"})
    assert response.status_code == 401


def test_me_returns_current_user(client):
    tokens = register_and_login(client)
    response = client.get("/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


def test_me_without_token_returns_401(client):
    assert client.get("/users/me").status_code == 401


def test_me_with_refresh_token_returns_401(client):
    tokens = register_and_login(client)
    response = client.get("/users/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert response.status_code == 401


def test_me_with_expired_token_returns_401(client):
    expired = JwtTokenService(secret="test-secret", access_ttl_seconds=-10, refresh_ttl_seconds=-10)
    token = expired.issue_access(uuid4())
    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_me_with_token_for_deleted_user_returns_404(client, app):
    service = JwtTokenService(secret="test-secret", access_ttl_seconds=900, refresh_ttl_seconds=900)
    token = service.issue_access(uuid4())
    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


def test_refresh_returns_new_pair(client):
    tokens = register_and_login(client)
    response = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] and body["refresh_token"]


def test_refresh_with_access_token_returns_401(client):
    tokens = register_and_login(client)
    response = client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_auth_http.py -v`
Expected: FAIL (either `TypeError: create_app() got an unexpected keyword argument` or 404s).

- [ ] **Step 3: Write the composition root**

`backend/src/app/presentation/dependencies.py`:
```python
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import HTTPConnection

from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.token_service import InvalidToken, TokenService
from app.application.ports.unit_of_work import UnitOfWork
from app.infrastructure.config import Settings
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.realtime.hub import ConnectionHub
from app.infrastructure.security.argon2_hasher import Argon2PasswordHasher
from app.infrastructure.security.jwt_token_service import JwtTokenService

_bearer = HTTPBearer(auto_error=False)


def get_settings(conn: HTTPConnection) -> Settings:
    return conn.app.state.settings


def get_uow(conn: HTTPConnection) -> UnitOfWork:
    return SqlAlchemyUnitOfWork(conn.app.state.session_factory)


def get_hasher() -> PasswordHasher:
    return Argon2PasswordHasher()


def get_token_service(settings: Annotated[Settings, Depends(get_settings)]) -> TokenService:
    return JwtTokenService(
        secret=settings.jwt_secret,
        access_ttl_seconds=settings.jwt_access_ttl_seconds,
        refresh_ttl_seconds=settings.jwt_refresh_ttl_seconds,
    )


def get_hub(conn: HTTPConnection) -> ConnectionHub:
    return conn.app.state.hub


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> UUID:
    if credentials is None:
        raise _unauthorized("Not authenticated")
    try:
        payload = tokens.decode(credentials.credentials)
    except InvalidToken as exc:
        raise _unauthorized("Invalid or expired token") from exc
    if payload.type != "access":
        raise _unauthorized("Invalid token type")
    return payload.user_id


SettingsDep = Annotated[Settings, Depends(get_settings)]
UowDep = Annotated[UnitOfWork, Depends(get_uow)]
HasherDep = Annotated[PasswordHasher, Depends(get_hasher)]
TokenServiceDep = Annotated[TokenService, Depends(get_token_service)]
HubDep = Annotated[ConnectionHub, Depends(get_hub)]
CurrentUserIdDep = Annotated[UUID, Depends(get_current_user_id)]
```

- [ ] **Step 4: Write the error mapping**

`backend/src/app/presentation/http/errors.py`:
```python
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.domain.errors import EmailAlreadyUsed, InvalidCredentials, UserNotFound


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(EmailAlreadyUsed)
    async def _email_already_used(_: Request, __: EmailAlreadyUsed) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT, content={"detail": "Email already used"}
        )

    @app.exception_handler(InvalidCredentials)
    async def _invalid_credentials(_: Request, __: InvalidCredentials) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid credentials"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(UserNotFound)
    async def _user_not_found(_: Request, __: UserNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND, content={"detail": "User not found"}
        )
```

- [ ] **Step 5: Write the auth and users routers**

`backend/src/app/presentation/http/auth.py`:
```python
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field

from app.application.auth.dtos import LoginInput, RegisterInput, TokenPair, UserOutput
from app.application.auth.login import LoginUser
from app.application.auth.refresh import RefreshTokens
from app.application.auth.register import RegisterUser
from app.presentation.dependencies import HasherDep, HubDep, TokenServiceDep, UowDep

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    created_at: datetime

    @classmethod
    def from_output(cls, output: UserOutput) -> "UserResponse":
        return cls(id=output.id, email=output.email, created_at=output.created_at)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

    @classmethod
    def from_pair(cls, pair: TokenPair) -> "TokenPairResponse":
        return cls(access_token=pair.access_token, refresh_token=pair.refresh_token)


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
async def register(body: RegisterRequest, uow: UowDep, hasher: HasherDep) -> UserResponse:
    output = await RegisterUser(uow=uow, hasher=hasher).execute(
        RegisterInput(email=body.email, password=body.password)
    )
    return UserResponse.from_output(output)


@router.post("/login", response_model=TokenPairResponse)
async def login(
    body: LoginRequest, uow: UowDep, hasher: HasherDep, tokens: TokenServiceDep, hub: HubDep
) -> TokenPairResponse:
    pair = await LoginUser(uow=uow, hasher=hasher, tokens=tokens, broadcaster=hub).execute(
        LoginInput(email=body.email, password=body.password)
    )
    return TokenPairResponse.from_pair(pair)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(body: RefreshRequest, uow: UowDep, tokens: TokenServiceDep) -> TokenPairResponse:
    pair = await RefreshTokens(uow=uow, tokens=tokens).execute(body.refresh_token)
    return TokenPairResponse.from_pair(pair)
```

`backend/src/app/presentation/http/users.py`:
```python
from fastapi import APIRouter

from app.application.users.get_me import GetCurrentUser
from app.presentation.dependencies import CurrentUserIdDep, UowDep
from app.presentation.http.auth import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def me(user_id: CurrentUserIdDep, uow: UowDep) -> UserResponse:
    output = await GetCurrentUser(uow=uow).execute(user_id)
    return UserResponse.from_output(output)
```

- [ ] **Step 6: Wire everything in the app factory**

Replace `backend/src/app/presentation/main.py`:
```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.infrastructure.config import Settings
from app.infrastructure.db.engine import create_engine, create_session_factory
from app.infrastructure.realtime.hub import ConnectionHub
from app.presentation.http import auth, health, users
from app.presentation.http.errors import register_error_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(title="sentinel-x", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = create_session_factory(engine)
    app.state.hub = ConnectionHub()

    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    return app


app = create_app()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all PASS (unit + integration).

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add backend
git commit -m "feat(backend): add auth and users HTTP routes with composition root

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: WebSocket endpoint

**Files:**
- Create: `backend/src/app/presentation/ws/__init__.py` (empty)
- Create: `backend/src/app/presentation/ws/router.py`
- Modify: `backend/src/app/presentation/main.py`
- Test: `backend/tests/integration/test_ws.py`

**Interfaces:**
- Consumes: `get_token_service`, `get_hub` (Task 8), `ConnectionHub` (Task 7), `InvalidToken` (Task 3).
- Produces: `GET /ws?token=<access>` WebSocket route. Client → server JSON: `{"type":"ping"}` answers `{"type":"pong"}`; any other JSON is echoed as `{"type":"echo","data":<msg>}`; invalid JSON answers `{"type":"error","detail":"invalid json"}`. Server → client: events pushed through the hub.

- [ ] **Step 1: Write the failing tests**

`backend/tests/integration/test_ws.py`:
```python
import pytest
from starlette.websockets import WebSocketDisconnect

from tests.integration.conftest import register_and_login


def test_ws_without_token_is_closed_with_1008(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws"):
            pass
    assert exc.value.code == 1008


def test_ws_with_bad_token_is_closed_with_1008(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws?token=garbage"):
            pass
    assert exc.value.code == 1008


def test_ws_with_refresh_token_is_closed_with_1008(client):
    tokens = register_and_login(client)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws?token={tokens['refresh_token']}"):
            pass
    assert exc.value.code == 1008


def test_ws_ping_pong(client):
    tokens = register_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_ws_echoes_other_messages(client):
    tokens = register_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        ws.send_json({"type": "custom", "value": 42})
        assert ws.receive_json() == {"type": "echo", "data": {"type": "custom", "value": 42}}


def test_ws_invalid_json_returns_error_and_keeps_connection(client):
    tokens = register_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        ws.send_text("{not json")
        assert ws.receive_json() == {"type": "error", "detail": "invalid json"}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_ws_receives_logged_in_event(client):
    tokens = register_and_login(client, email="alice@example.com")
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        register_and_login(client, email="bob@example.com")
        event = ws.receive_json()
        assert event["type"] == "user.logged_in"
        assert "user_id" in event


def test_ws_disconnect_removes_connection_from_hub(client, app):
    tokens = register_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}"):
        assert app.state.hub.connection_count == 1
    assert app.state.hub.connection_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_ws.py -v`
Expected: FAIL (`WebSocketDisconnect` with code 403 or similar, since `/ws` does not exist yet).

- [ ] **Step 3: Write the WebSocket router**

`backend/src/app/presentation/ws/__init__.py`: empty.

`backend/src/app/presentation/ws/router.py`:
```python
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.application.ports.token_service import InvalidToken, TokenService
from app.presentation.dependencies import HubDep, TokenServiceDep

router = APIRouter(tags=["realtime"])


def _authenticate(token: str | None, tokens: TokenService) -> UUID | None:
    if not token:
        return None
    try:
        payload = tokens.decode(token)
    except InvalidToken:
        return None
    if payload.type != "access":
        return None
    return payload.user_id


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    tokens: TokenServiceDep,
    hub: HubDep,
    token: Annotated[str | None, Query()] = None,
) -> None:
    user_id = _authenticate(token, tokens)
    if user_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    hub.connect(user_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "invalid json"})
                continue
            if isinstance(message, dict) and message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "echo", "data": message})
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(user_id, websocket)
```

- [ ] **Step 4: Register the router**

In `backend/src/app/presentation/main.py`, add the import and include:
```python
from app.presentation.ws import router as ws_router
```
and after `app.include_router(users.router)`:
```python
    app.include_router(ws_router.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add backend
git commit -m "feat(backend): add authenticated WebSocket endpoint

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Dockerfile, compose stack, nginx proxy and smoke test

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/.dockerignore`
- Create: `backend/scripts/smoke.py`
- Create: `scripts/smoke.sh` (repo root)
- Create: `nginx/default.conf` (repo root)
- Modify: `compose.yml` (repo root)
- Modify: `.gitignore` (repo root, create if missing)
- Create: `README.md` (repo root)

**Interfaces:**
- Consumes: the full backend from Tasks 1–9, `backend/.env.example` from Task 5.
- Produces: `docker compose up -d` starts `db`, `api`, `web`; `http://<host>:8080/api/health` and `ws://<host>:8080/ws` work through nginx; `scripts/smoke.sh [base_url]` exercises register → login → me → ws ping.

- [ ] **Step 1: Write the Dockerfile and .dockerignore**

`backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

RUN useradd --create-home app && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.presentation.main:app --host 0.0.0.0 --port 8000"]
```

`backend/.dockerignore`:
```
.venv
__pycache__
*.pyc
.pytest_cache
.ruff_cache
.env
tests
scripts
```

- [ ] **Step 2: Write the nginx config**

`nginx/default.conf`:
```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;

    location /api/ {
        proxy_pass http://api:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws {
        proxy_pass http://api:8000/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
    }

    location / {
        root /usr/share/nginx/html;
        index index.html;
    }
}
```

- [ ] **Step 3: Write the full compose file**

Replace `compose.yml` at the repository root:
```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: sentinel
      POSTGRES_PASSWORD: sentinel
      POSTGRES_DB: sentinel
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/postgres/init-test-db.sql:/docker-entrypoint-initdb.d/init-test-db.sql:ro
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sentinel -d sentinel"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped

  api:
    build: ./backend
    env_file: ./backend/.env
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

  web:
    image: nginx:alpine
    ports:
      - "8080:80"
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - api
    restart: unless-stopped

volumes:
  pgdata:
```

Root `.gitignore` (create or append):
```
backend/.env
```

- [ ] **Step 4: Write the smoke test**

`backend/scripts/smoke.py`:
```python
"""End-to-end smoke test against a running stack.

Usage: python scripts/smoke.py [base_url]   (default http://localhost:8080)
"""

import asyncio
import json
import sys
import uuid

import httpx
import websockets


async def main(base_url: str) -> None:
    api = f"{base_url.rstrip('/')}/api"
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://").rstrip("/") + "/ws"
    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    password = "smoke-secret-123"

    async with httpx.AsyncClient(timeout=10) as client:
        health = await client.get(f"{api}/health")
        assert health.status_code == 200, health.text
        print("health      OK")

        register = await client.post(
            f"{api}/auth/register", json={"email": email, "password": password}
        )
        assert register.status_code == 201, register.text
        print("register    OK")

        login = await client.post(f"{api}/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        access = login.json()["access_token"]
        print("login       OK")

        me = await client.get(f"{api}/users/me", headers={"Authorization": f"Bearer {access}"})
        assert me.status_code == 200 and me.json()["email"] == email, me.text
        print("me          OK")

    async with websockets.connect(f"{ws_url}?token={access}") as ws:
        await ws.send(json.dumps({"type": "ping"}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert reply == {"type": "pong"}, reply
        print("ws ping     OK")

    print("smoke test passed")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"))
```

`scripts/smoke.sh`:
```bash
#!/usr/bin/env sh
# Runs the end-to-end smoke test against a running compose stack.
# Usage: scripts/smoke.sh [base_url]   (default http://localhost:8080)
set -eu
cd "$(dirname "$0")/../backend"
exec uv run python scripts/smoke.py "${1:-http://localhost:8080}"
```

Run: `chmod +x scripts/smoke.sh`

- [ ] **Step 5: Create the local .env and build the stack**

Run from the repository root:
```bash
cp backend/.env.example backend/.env
docker compose build api
docker compose up -d
docker compose ps
```
Expected: three services up, `db` healthy, `api` logs end with `Application startup complete`. Check with `docker compose logs api | tail -5`.

- [ ] **Step 6: Run the smoke test**

Run: `scripts/smoke.sh`
Expected output:
```
health      OK
register    OK
login       OK
me          OK
ws ping     OK
smoke test passed
```

- [ ] **Step 7: Verify nginx still serves its welcome page**

Run: `curl -s http://localhost:8080/ | grep -o '<title>.*</title>'`
Expected: `<title>Welcome to nginx!</title>`

- [ ] **Step 8: Write the README**

`README.md`:
~~~markdown
# sentinel-x

Backend FastAPI (clean architecture, JWT auth, WebSocket) servi par nginx, pensé pour un Raspberry Pi avec Docker rootless.

## Démarrer

```sh
cp backend/.env.example backend/.env   # puis changer JWT_SECRET
docker compose up -d
scripts/smoke.sh                        # register → login → me → ws ping
```

- API via nginx : `http://<hôte>:8080/api/...` (par exemple `/api/health`)
- WebSocket : `ws://<hôte>:8080/ws?token=<access_token>`
- Page d'accueil nginx : `http://<hôte>:8080/`

## Développer

```sh
docker compose up -d db
cd backend
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .
```

Les tests d'intégration utilisent la base `sentinel_test` créée par `docker/postgres/init-test-db.sql`.

## Structure

- `backend/src/app/domain` : entités et interfaces de dépôts, Python pur
- `backend/src/app/application` : use cases et ports
- `backend/src/app/infrastructure` : SQLAlchemy, Argon2, JWT, hub WebSocket, settings
- `backend/src/app/presentation` : FastAPI (HTTP, WS, composition root)
- `docs/superpowers/specs` : spécifications de design
~~~

- [ ] **Step 9: Tear down and commit**

```bash
docker compose down
git add backend/Dockerfile backend/.dockerignore backend/scripts scripts nginx compose.yml .gitignore README.md
git commit -m "feat: add Dockerfile, compose stack with nginx proxy and smoke test

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Final verification (after Task 10)

From the repository root:

```bash
cd backend && uv run pytest -v && uv run ruff check . && cd ..
grep -rE "fastapi|sqlalchemy|jwt|pydantic|starlette|pwdlib" backend/src/app/domain backend/src/app/application || echo CLEAN
docker compose up -d && scripts/smoke.sh && docker compose down
```

All four spec success criteria must hold: compose starts cleanly, smoke test passes, pytest passes, dependency-rule grep is clean.
