from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.user import User


@dataclass(frozen=True, slots=True)
class RegisterInput:
    email: str
    password: str


@dataclass(frozen=True, slots=True)
class LoginInput:
    email: str
    password: str


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class UserOutput:
    id: UUID
    email: str
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> UserOutput:
        return cls(id=user.id, email=user.email, created_at=user.created_at)
