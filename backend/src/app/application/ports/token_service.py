from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

TokenType = Literal["access", "refresh"]


class InvalidToken(Exception):
    """Raised when a token cannot be decoded or has expired."""


@dataclass(frozen=True, slots=True)
class TokenPayload:
    user_id: UUID
    type: str


class TokenService(Protocol):
    def issue_access(self, user_id: UUID) -> str: ...

    def issue_refresh(self, user_id: UUID) -> str: ...

    def decode(self, token: str) -> TokenPayload: ...
