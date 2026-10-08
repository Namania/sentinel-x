from tests.integration.conftest import DEVICE_HEADERS, create_user_and_login

HOT = {"device_id": "esp-interieur", "temperature": {"humidity": 48.0, "temp": 30.4}}
COOL = {"device_id": "esp-interieur", "temperature": {"humidity": 48.0, "temp": 29.0}}


def auth(client):
    return {"Authorization": f"Bearer {create_user_and_login(client)['access_token']}"}


def test_alerts_require_a_token(client):
    assert client.get("/alerts").status_code == 401
    assert client.get("/alerts/summary").status_code == 401


def test_alerts_open_then_resolve_through_readings(client):
    headers = auth(client)
    assert client.get("/alerts", headers=headers).json() == []
    assert client.get("/alerts/summary", headers=headers).json() == {"open": 0}

    assert client.post("/sensors/readings", json=HOT, headers=DEVICE_HEADERS).status_code == 201
    alerts = client.get("/alerts", headers=headers).json()
    assert len(alerts) == 1
    assert (alerts[0]["metric"], alerts[0]["direction"], alerts[0]["threshold"]) == (
        "temperature",
        "high",
        30.0,
    )
    assert alerts[0]["resolved_at"] is None
    assert client.get("/alerts/summary", headers=headers).json() == {"open": 1}
    assert client.get("/alerts?status=resolved", headers=headers).json() == []

    assert client.post("/sensors/readings", json=COOL, headers=DEVICE_HEADERS).status_code == 201
    resolved = client.get("/alerts?status=resolved&device_id=esp-interieur", headers=headers).json()
    assert len(resolved) == 1 and resolved[0]["resolved_value"] == 29.0
    assert client.get("/alerts?status=open", headers=headers).json() == []
    assert client.get("/alerts?device_id=esp-exterieur", headers=headers).json() == []


def test_alert_events_follow_the_reading_event_on_the_websocket(client):
    tokens = create_user_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        client.post("/sensors/readings", json=HOT, headers=DEVICE_HEADERS)
        assert ws.receive_json()["type"] == "sensor.reading"
        opened = ws.receive_json()
        assert opened["type"] == "alert.opened"
        assert opened["data"]["opened_at"].endswith("Z")
        assert ws.receive_json()["type"] == "siren.state"  # high temperature sounds the siren
        client.post("/sensors/readings", json=COOL, headers=DEVICE_HEADERS)
        assert ws.receive_json()["type"] == "sensor.reading"
        assert ws.receive_json()["type"] == "alert.resolved"
        assert ws.receive_json()["type"] == "siren.state"


def test_limit_is_validated(client):
    headers = auth(client)
    assert client.get("/alerts?limit=0", headers=headers).status_code == 422
    assert client.get("/alerts?status=bogus", headers=headers).status_code == 422


def test_alerts_device_filter_accepts_ip_device_ids(client):
    headers = auth(client)
    assert client.get("/alerts?device_id=ip:fe80::1", headers=headers).status_code == 200
    assert client.get("/alerts?device_id=ip:203.0.113.5", headers=headers).json() == []
