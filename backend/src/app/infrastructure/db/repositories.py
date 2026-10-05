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
