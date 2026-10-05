from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import HTTPConnection

from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.token_service import InvalidToken, TokenService
from app.application.ports.unit_of_work import UnitOfWork
from app.infrastructure.config import Settings
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.realtime.hub import ConnectionHub
from app.infrastructure.security.argon2_hasher import Argon2PasswordHasher
from app.infrastructure.security.jwt_token_service import JwtTokenService

_bearer = HTTPBearer(auto_error=False)


def get_settings(conn: HTTPConnection) -> Settings:
    return conn.app.state.settings


def get_uow(conn: HTTPConnection) -> UnitOfWork:
    return SqlAlchemyUnitOfWork(conn.app.state.session_factory)


def get_hasher() -> PasswordHasher:
    return Argon2PasswordHasher()


def get_token_service(settings: Annotated[Settings, Depends(get_settings)]) -> TokenService:
    return JwtTokenService(
        secret=settings.jwt_secret,
        access_ttl_seconds=settings.jwt_access_ttl_seconds,
        refresh_ttl_seconds=settings.jwt_refresh_ttl_seconds,
    )


def get_hub(conn: HTTPConnection) -> ConnectionHub:
    return conn.app.state.hub


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> UUID:
    if credentials is None:
        raise _unauthorized("Not authenticated")
    try:
        payload = tokens.decode(credentials.credentials)
    except InvalidToken as exc:
        raise _unauthorized("Invalid or expired token") from exc
    if payload.type != "access":
        raise _unauthorized("Invalid token type")
    return payload.user_id


SettingsDep = Annotated[Settings, Depends(get_settings)]
UowDep = Annotated[UnitOfWork, Depends(get_uow)]
HasherDep = Annotated[PasswordHasher, Depends(get_hasher)]
TokenServiceDep = Annotated[TokenService, Depends(get_token_service)]
HubDep = Annotated[ConnectionHub, Depends(get_hub)]
CurrentUserIdDep = Annotated[UUID, Depends(get_current_user_id)]
