from tests.integration.conftest import DEVICE_HEADERS, create_user_and_login

GAS_ALERT = {"device_id": "esp-interieur", "gaz": {"mostGaz": True, "quantity": 1800}}
GAS_OK = {"device_id": "esp-interieur", "gaz": {"mostGaz": False, "quantity": 400}}
HUMID = {"device_id": "esp-interieur", "temperature": {"humidity": 75.0, "temp": 22.0}}


def auth(client):
    return {"Authorization": f"Bearer {create_user_and_login(client)['access_token']}"}


def test_siren_routes_require_a_token(client):
    assert client.get("/alerts/siren").status_code == 401
    assert client.post("/alerts/siren/mute").status_code == 401
    assert client.delete("/alerts/siren/mute").status_code == 401


def test_siren_follows_gas_alerts_and_the_mute(client):
    headers = auth(client)
    assert client.get("/alerts/siren", headers=headers).json() == {
        "on": False,
        "reason": None,
        "open": 0,
        "muted_until": None,
    }
    client.post("/sensors/readings", json=HUMID, headers=DEVICE_HEADERS)  # humidity: no siren
    assert client.get("/alerts/siren", headers=headers).json()["on"] is False

    client.post("/sensors/readings", json=GAS_ALERT, headers=DEVICE_HEADERS)
    state = client.get("/alerts/siren", headers=headers).json()
    assert (state["on"], state["reason"], state["open"]) == (True, "gas", 2)

    muted = client.post("/alerts/siren/mute", headers=headers).json()
    assert muted["on"] is False and muted["muted_until"] is not None
    assert client.delete("/alerts/siren/mute", headers=headers).json()["on"] is True

    client.post("/sensors/readings", json=GAS_OK, headers=DEVICE_HEADERS)
    assert client.get("/alerts/siren", headers=headers).json()["on"] is False


def test_siren_events_follow_alert_events_on_the_websocket(client):
    tokens = create_user_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        client.post("/sensors/readings", json=GAS_ALERT, headers=DEVICE_HEADERS)
        assert [ws.receive_json()["type"] for _ in range(3)] == [
            "sensor.reading",
            "alert.opened",
            "siren.state",
        ]
        client.post("/alerts/siren/mute", headers=headers)
        event = ws.receive_json()
        assert event["type"] == "siren.state" and event["data"]["on"] is False
        client.delete("/alerts/siren/mute", headers=headers)
        assert ws.receive_json()["data"]["on"] is True
