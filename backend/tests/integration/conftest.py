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
