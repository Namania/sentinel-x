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
