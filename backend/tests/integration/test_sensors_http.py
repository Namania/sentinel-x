from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.presentation.main import create_app
from tests.integration.conftest import DEVICE_HEADERS, TEST_SETTINGS, create_user_and_login

BODY = {
    "device_id": "esp-interieur",
    "gaz": {"mostGaz": False, "quantity": 412},
    "temperature": {"humidity": 48.5, "temp": 22.9},
}


def auth(client):
    return {"Authorization": f"Bearer {create_user_and_login(client)['access_token']}"}


def test_device_posts_a_reading(client):
    response = client.post("/sensors/readings", json=BODY, headers=DEVICE_HEADERS)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["device_id"] == "esp-interieur"
    assert (data["temperature_c"], data["humidity_pct"], data["gas_ppm"], data["gas_alert"]) == (
        22.9,
        48.5,
        412,
        False,
    )
    assert data["recorded_at"].endswith("+00:00") or data["recorded_at"].endswith("Z")


def test_device_timestamp_is_kept_and_naive_times_are_utc(client):
    body = {**BODY, "recorded_at": "2026-10-06T09:00:00"}
    response = client.post("/sensors/readings", json=body, headers=DEVICE_HEADERS)
    assert response.status_code == 201
    assert response.json()["recorded_at"] == "2026-10-06T09:00:00Z"


def test_heartbeat_without_metrics_is_stored(client):
    response = client.post(
        "/sensors/readings", json={"device_id": "esp-interieur"}, headers=DEVICE_HEADERS
    )
    assert response.status_code == 201
    data = response.json()
    assert (data["temperature_c"], data["humidity_pct"], data["gas_ppm"], data["gas_alert"]) == (
        None,
        None,
        None,
        False,
    )


def test_post_requires_the_device_key(client):
    assert client.post("/sensors/readings", json=BODY).status_code == 401
    bad = client.post("/sensors/readings", json=BODY, headers={"X-Device-Key": "nope"})
    assert bad.status_code == 401


def test_post_rejects_out_of_range_values(client):
    body = {**BODY, "temperature": {"humidity": 101, "temp": 20}}
    response = client.post("/sensors/readings", json=body, headers=DEVICE_HEADERS)
    assert response.status_code == 422


def test_post_is_unavailable_without_a_configured_key():
    settings = TEST_SETTINGS.model_copy(update={"device_api_key": None})
    with TestClient(create_app(settings)) as unconfigured:
        response = unconfigured.post("/sensors/readings", json=BODY, headers=DEVICE_HEADERS)
    assert response.status_code == 503


def test_history_raw_and_bucketed(client):
    headers = auth(client)
    t0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
    for minutes, temp in [(0, 20.0), (1, 22.0), (6, 30.0)]:
        body = {
            **BODY,
            "recorded_at": (t0 + timedelta(minutes=minutes)).isoformat(),
            "temperature": {"humidity": 50, "temp": temp},
        }
        posted = client.post("/sensors/readings", json=body, headers=DEVICE_HEADERS)
        assert posted.status_code == 201

    raw = client.get(
        "/sensors/readings",
        params={
            "device_id": "esp-interieur",
            "from": t0.isoformat(),
            "to": (t0 + timedelta(minutes=10)).isoformat(),
        },
        headers=headers,
    )
    assert raw.status_code == 200
    assert [r["temperature_c"] for r in raw.json()] == [20.0, 22.0, 30.0]

    buckets = client.get(
        "/sensors/readings",
        params={
            "device_id": "esp-interieur",
            "from": "2026-10-06T09:00:00",
            "to": "2026-10-06T09:10:00",
            "bucket": "5m",
        },
        headers=headers,
    )
    assert buckets.status_code == 200
    assert [(b["count"], b["temperature_avg"]) for b in buckets.json()] == [(2, 21.0), (1, 30.0)]
    assert buckets.json()[0]["bucket_start"] == "2026-10-06T09:00:00Z"


def test_history_defaults_to_the_last_hour(client):
    headers = auth(client)
    old = {**BODY, "recorded_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat()}
    assert client.post("/sensors/readings", json=old, headers=DEVICE_HEADERS).status_code == 201
    assert client.post("/sensors/readings", json=BODY, headers=DEVICE_HEADERS).status_code == 201
    response = client.get(
        "/sensors/readings", params={"device_id": "esp-interieur"}, headers=headers
    )
    assert len(response.json()) == 1


def test_history_rejects_unknown_bucket(client):
    response = client.get(
        "/sensors/readings",
        params={"device_id": "esp-interieur", "bucket": "2m"},
        headers=auth(client),
    )
    assert response.status_code == 422


def test_history_requires_a_user(client):
    assert client.get("/sensors/readings", params={"device_id": "esp-interieur"}).status_code == 401


def test_latest_and_devices(client):
    headers = auth(client)
    client.post("/sensors/readings", json=BODY, headers=DEVICE_HEADERS)
    client.post("/sensors/readings", json={**BODY, "device_id": "esp-ext"}, headers=DEVICE_HEADERS)
    latest = client.get("/sensors/latest", headers=headers).json()
    assert sorted(r["device_id"] for r in latest) == ["esp-ext", "esp-interieur"]
    devices = client.get("/sensors/devices", headers=headers).json()
    assert [d["device_id"] for d in devices] == ["esp-ext", "esp-interieur"]
    assert "last_seen" in devices[0]


def test_new_reading_is_pushed_on_the_websocket(client):
    tokens = create_user_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        response = client.post("/sensors/readings", json=BODY, headers=DEVICE_HEADERS)
        assert response.status_code == 201
        event = ws.receive_json()
    assert event["type"] == "sensor.reading"
    assert event["data"]["id"] == response.json()["id"]
    assert event["data"]["gas_ppm"] == 412


def test_post_with_a_non_ascii_key_is_refused_not_a_server_error(client):
    # httpx only lets raw bytes carry non-ASCII header values, like a real client would.
    headers = {b"X-Device-Key": "clé-ünicode-0123456789".encode()}
    response = client.post("/sensors/readings", json=BODY, headers=headers)
    assert response.status_code == 401
