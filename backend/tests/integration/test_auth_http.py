from uuid import uuid4

from app.infrastructure.security.jwt_token_service import JwtTokenService
from tests.integration.conftest import register_and_login


def test_register_returns_201_with_user(client):
    response = client.post(
        "/auth/register", json={"email": "Alice@Example.com", "password": "secret123"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert "id" in body and "created_at" in body
    assert "password" not in body and "password_hash" not in body


def test_register_duplicate_email_returns_409(client):
    client.post("/auth/register", json={"email": "alice@example.com", "password": "secret123"})
    response = client.post(
        "/auth/register", json={"email": " ALICE@example.com ", "password": "secret123"}
    )
    assert response.status_code == 409


def test_register_short_password_returns_422(client):
    response = client.post(
        "/auth/register", json={"email": "alice@example.com", "password": "short"}
    )
    assert response.status_code == 422


def test_register_invalid_email_returns_422(client):
    response = client.post(
        "/auth/register", json={"email": "not-an-email", "password": "secret123"}
    )
    assert response.status_code == 422


def test_login_returns_token_pair(client):
    tokens = register_and_login(client)
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"] and tokens["refresh_token"]


def test_login_wrong_password_returns_401(client):
    client.post("/auth/register", json={"email": "alice@example.com", "password": "secret123"})
    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "wrong1234"}
    )
    assert response.status_code == 401


def test_me_returns_current_user(client):
    tokens = register_and_login(client)
    response = client.get(
        "/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


def test_me_without_token_returns_401(client):
    assert client.get("/users/me").status_code == 401


def test_me_with_refresh_token_returns_401(client):
    tokens = register_and_login(client)
    response = client.get(
        "/users/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )
    assert response.status_code == 401


def test_me_with_expired_token_returns_401(client):
    expired = JwtTokenService(
        secret="test-secret-0123456789-abcdefghijklmnop",
        access_ttl_seconds=-10,
        refresh_ttl_seconds=-10,
    )
    token = expired.issue_access(uuid4())
    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_me_with_token_for_deleted_user_returns_404(client, app):
    service = JwtTokenService(
        secret="test-secret-0123456789-abcdefghijklmnop",
        access_ttl_seconds=900,
        refresh_ttl_seconds=900,
    )
    token = service.issue_access(uuid4())
    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


def test_refresh_returns_new_pair(client):
    tokens = register_and_login(client)
    response = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] and body["refresh_token"]


def test_refresh_with_access_token_returns_401(client):
    tokens = register_and_login(client)
    response = client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert response.status_code == 401
