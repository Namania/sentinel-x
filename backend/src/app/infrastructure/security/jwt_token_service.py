from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from app.application.ports.token_service import InvalidToken, TokenPayload


class JwtTokenService:
    def __init__(
        self,
        secret: str,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
        algorithm: str = "HS256",
    ) -> None:
        self._secret = secret
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds
        self._algorithm = algorithm

    def issue_access(self, user_id: UUID) -> str:
        return self._issue(user_id, "access", self._access_ttl)

    def issue_refresh(self, user_id: UUID) -> str:
        return self._issue(user_id, "refresh", self._refresh_ttl)

    def decode(self, token: str) -> TokenPayload:
        try:
            claims = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.PyJWTError as exc:
            raise InvalidToken() from exc
        try:
            return TokenPayload(user_id=UUID(claims["sub"]), type=claims["type"])
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidToken() from exc

    def _issue(self, user_id: UUID, token_type: str, ttl_seconds: int) -> str:
        now = datetime.now(UTC)
        claims = {
            "sub": str(user_id),
            "type": token_type,
            "iat": now,
            "exp": now + timedelta(seconds=ttl_seconds),
        }
        return jwt.encode(claims, self._secret, algorithm=self._algorithm)
