import asyncio
import os
import threading
from collections.abc import Callable, Coroutine, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.infrastructure.config import Settings
from app.infrastructure.db.models import Base
from app.presentation.cli import create_user
from app.presentation.main import create_app

TEST_JWT_SECRET = "test-secret-0123456789-abcdefghijklmnop"

TEST_SETTINGS = Settings(
    postgres_host=os.environ.get("TEST_POSTGRES_HOST", "localhost"),
    postgres_port=int(os.environ.get("TEST_POSTGRES_PORT", "5432")),
    postgres_db=os.environ.get("TEST_POSTGRES_DB", "sentinel_test"),
    jwt_secret=TEST_JWT_SECRET,
    camera_stream_url=None,
)
TEST_DATABASE_URL = TEST_SETTINGS.database_url


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


@pytest.fixture(scope="session")
def app():
    return create_app(TEST_SETTINGS)


@pytest.fixture(scope="session")
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def create_user_and_login(client: TestClient, email: str = "alice@example.com") -> dict:
    _run_isolated(lambda: create_user(email, "secret123", TEST_SETTINGS))
    response = client.post("/auth/login", json={"email": email, "password": "secret123"})
    assert response.status_code == 200, response.text
    return response.json()
