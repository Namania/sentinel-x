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
