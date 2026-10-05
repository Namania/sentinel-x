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
