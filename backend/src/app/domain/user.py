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
