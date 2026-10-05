from uuid import uuid4

import pytest

from app.application.ports.token_service import InvalidToken
from app.infrastructure.security.jwt_token_service import JwtTokenService


@pytest.fixture
def service() -> JwtTokenService:
    return JwtTokenService(
        secret="test-secret-0123456789-0123456789-xx",
        access_ttl_seconds=900,
        refresh_ttl_seconds=3600,
    )


def test_access_token_round_trip(service):
    user_id = uuid4()
    payload = service.decode(service.issue_access(user_id))
    assert payload.user_id == user_id
    assert payload.type == "access"


def test_refresh_token_round_trip(service):
    user_id = uuid4()
    payload = service.decode(service.issue_refresh(user_id))
    assert payload.user_id == user_id
    assert payload.type == "refresh"


def test_decode_rejects_wrong_secret(service):
    other = JwtTokenService(
        secret="other-secret-0123456789-0123456789-xx",
        access_ttl_seconds=900,
        refresh_ttl_seconds=3600,
    )
    token = other.issue_access(uuid4())
    with pytest.raises(InvalidToken):
        service.decode(token)


def test_decode_rejects_expired_token():
    expired = JwtTokenService(
        secret="test-secret-0123456789-0123456789-xx",
        access_ttl_seconds=-10,
        refresh_ttl_seconds=-10,
    )
    token = expired.issue_access(uuid4())
    with pytest.raises(InvalidToken):
        expired.decode(token)


def test_decode_rejects_garbage(service):
    with pytest.raises(InvalidToken):
        service.decode("not.a.jwt")
