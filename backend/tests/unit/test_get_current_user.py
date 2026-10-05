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
