from datetime import UTC, datetime

from app.application.server.health import HealthHistory, ServerHealth
from tests.integration.conftest import create_user_and_login


def auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_server_health_requires_a_token(client):
    assert client.get("/server/health").status_code == 401


def test_server_health_is_empty_before_the_first_sample(client, app):
    saved, app.state.server_health = app.state.server_health, HealthHistory()
    try:
        response = client.get("/server/health", headers=auth(create_user_and_login(client)))
        assert response.status_code == 200
        assert response.json() == {"latest": None, "history": []}
    finally:
        app.state.server_health = saved


def test_server_health_returns_the_latest_sample_and_the_history(client, app):
    history = HealthHistory()
    history.append(
        ServerHealth(
            recorded_at=datetime(2026, 10, 6, 9, 0, 5, tzinfo=UTC),
            cpu_pct=12.5,
            mem_total_bytes=8_589_934_592,
            mem_used_bytes=2_147_483_648,
            disk_total_bytes=62_000_000_000,
            disk_used_bytes=21_000_000_000,
            temperature_c=48.2,
            load_1=0.42,
            load_5=0.38,
            load_15=0.31,
            uptime_s=86_400,
        )
    )
    saved, app.state.server_health = app.state.server_health, history
    try:
        body = client.get("/server/health", headers=auth(create_user_and_login(client))).json()
    finally:
        app.state.server_health = saved
    assert body["latest"]["cpu_pct"] == 12.5
    assert body["latest"]["recorded_at"].startswith("2026-10-06T09:00:05")
    assert body["latest"]["temperature_c"] == 48.2
    assert body["history"] == [body["latest"]]


def test_openapi_lists_server_health(client):
    schema = client.get("/openapi.json").json()
    assert "/server/health" in schema["paths"]
    assert schema["paths"]["/server/health"]["get"]["tags"] == ["server"]
