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
    output = await use_case.execute(
        RegisterInput(email=" Alice@Example.COM ", password="secret123")
    )
    assert output.email == "alice@example.com"
    assert await uow.users.get_by_email("alice@example.com") is not None


async def test_register_rejects_duplicate_email_case_insensitive(use_case):
    await use_case.execute(RegisterInput(email="alice@example.com", password="secret123"))
    with pytest.raises(EmailAlreadyUsed):
        await use_case.execute(RegisterInput(email="ALICE@example.com", password="other123"))
