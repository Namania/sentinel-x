import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import HTTPConnection

from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.token_service import InvalidToken, TokenService
from app.application.ports.unit_of_work import UnitOfWork
from app.infrastructure.camera.relay import CameraRelay
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


def get_camera_relay(conn: HTTPConnection) -> CameraRelay | None:
    return conn.app.state.camera_relay


def decode_access_token(token: str | None, tokens: TokenService) -> UUID | None:
    """User id carried by a valid access token, None for anything else."""
    if not token:
        return None
    try:
        payload = tokens.decode(token)
    except InvalidToken:
        return None
    if payload.type != "access":
        return None
    return payload.user_id


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


def get_current_user_id_from_header_or_query(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
    token: Annotated[str | None, Query()] = None,
) -> UUID:
    """Like `get_current_user_id`, but also accepts `?token=` for `<img>`/`<video>` tags,
    which cannot send an Authorization header."""
    raw = credentials.credentials if credentials is not None else token
    if raw is None:
        raise _unauthorized("Not authenticated")
    user_id = decode_access_token(raw, tokens)
    if user_id is None:
        raise _unauthorized("Invalid or expired token")
    return user_id


def require_device_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_device_key: Annotated[str | None, Header(alias="X-Device-Key")] = None,
) -> None:
    """Guard for device ingestion routes: a shared key, never a user token."""
    if not settings.device_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Device ingestion not configured",
        )
    if x_device_key is None or not secrets.compare_digest(x_device_key, settings.device_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device key")


SettingsDep = Annotated[Settings, Depends(get_settings)]
UowDep = Annotated[UnitOfWork, Depends(get_uow)]
HasherDep = Annotated[PasswordHasher, Depends(get_hasher)]
TokenServiceDep = Annotated[TokenService, Depends(get_token_service)]
HubDep = Annotated[ConnectionHub, Depends(get_hub)]
CurrentUserIdDep = Annotated[UUID, Depends(get_current_user_id)]
StreamUserIdDep = Annotated[UUID, Depends(get_current_user_id_from_header_or_query)]
CameraRelayDep = Annotated[CameraRelay | None, Depends(get_camera_relay)]
DeviceKeyDep = Annotated[None, Depends(require_device_key)]
