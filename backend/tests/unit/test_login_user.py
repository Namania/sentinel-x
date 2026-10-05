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
