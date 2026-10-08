from datetime import UTC, datetime, timedelta

from tests.integration.conftest import DEVICE_HEADERS, create_user_and_login


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


# Recent timestamps: an attempt older than SSH_ALERT_QUIET_MINUTES resolves its alert at once.
NOW = datetime.now(UTC).replace(microsecond=412000)

ACCEPTED = {
    "journal_id": "s=aa;i=1",
    "occurred_at": _iso(NOW - timedelta(seconds=30)),
    "outcome": "accepted",
    "username": "sentinel-x",
    "ip": "192.168.0.18",
    "port": 49513,
    "method": "publickey",
    "key_fingerprint": "SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls",
    "key_comment": "claude-audit@mac-namania",
    "reason": None,
}
REFUSED = {
    "journal_id": "s=aa;i=2",
    "occurred_at": _iso(NOW - timedelta(seconds=10)),
    "outcome": "refused",
    "username": "root",
    "ip": "203.0.113.5",
    "port": 51234,
    "reason": "key_rejected",
}


def auth(client):
    return {"Authorization": f"Bearer {create_user_and_login(client)['access_token']}"}


def post(client, body):
    return client.post("/ssh/events", json=body, headers=DEVICE_HEADERS)


def test_posting_requires_the_device_key_and_reading_requires_a_token(client):
    assert client.post("/ssh/events", json=ACCEPTED).status_code == 401
    assert client.get("/ssh/events").status_code == 401


def test_invalid_bodies_are_refused(client):
    assert post(client, {**REFUSED, "reason": None}).status_code == 422
    assert post(client, {**ACCEPTED, "reason": "unknown_user"}).status_code == 422
    assert post(client, {**REFUSED, "port": 70000}).status_code == 422
    assert post(client, {**REFUSED, "ip": "x" * 46}).status_code == 422
    assert client.get("/ssh/events?outcome=bogus", headers=auth(client)).status_code == 422


def test_an_accepted_connection_is_stored_once_and_listed(client):
    headers = auth(client)
    first = post(client, ACCEPTED)
    assert first.status_code == 201, first.text
    assert first.json()["key_comment"] == "claude-audit@mac-namania"
    assert first.json()["occurred_at"] == _iso(NOW - timedelta(seconds=30))
    again = post(client, ACCEPTED)
    assert again.status_code == 200
    rows = client.get("/ssh/events", headers=headers).json()
    assert len(rows) == 1 and rows[0]["journal_id"] == "s=aa;i=1"
    assert client.get("/alerts", headers=headers).json() == []


def test_a_refusal_opens_an_ssh_alert_for_the_ip(client):
    headers = auth(client)
    assert post(client, REFUSED).status_code == 201
    alerts = client.get("/alerts?status=open", headers=headers).json()
    assert len(alerts) == 1
    assert (alerts[0]["metric"], alerts[0]["device_id"], alerts[0]["peak_value"]) == (
        "ssh",
        "ip:203.0.113.5",
        1.0,
    )
    by_ip = client.get("/alerts?device_id=ip:203.0.113.5", headers=headers).json()
    assert by_ip[0]["id"] == alerts[0]["id"]
    later = {**REFUSED, "journal_id": "s=aa;i=3", "occurred_at": _iso(NOW - timedelta(seconds=5))}
    assert post(client, later).status_code == 201
    assert client.get("/alerts?status=open", headers=headers).json()[0]["peak_value"] == 2.0
    refused = client.get("/ssh/events?outcome=refused", headers=headers).json()
    assert [r["journal_id"] for r in refused] == ["s=aa;i=3", "s=aa;i=2"]
    assert client.get("/ssh/events?outcome=accepted", headers=headers).json() == []


def _next(ws, kind: str) -> dict:
    """The next event of that type; `siren.state` may or may not come with an alert change
    (the siren only speaks when its published state differs), so it is skipped."""
    while True:
        event = ws.receive_json()
        if event["type"] == "siren.state":
            continue
        assert event["type"] == kind, event
        return event


def test_events_reach_the_websocket(client):
    tokens = create_user_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        post(client, {**ACCEPTED, "journal_id": "s=ws;i=1"})
        assert _next(ws, "ssh.event")["data"]["ip"] == "192.168.0.18"
        post(client, {**REFUSED, "journal_id": "s=ws;i=2", "ip": "198.51.100.9"})
        _next(ws, "ssh.event")
        assert _next(ws, "alert.opened")["data"]["device_id"] == "ip:198.51.100.9"
        post(client, {**REFUSED, "journal_id": "s=ws;i=3", "ip": "198.51.100.9"})
        _next(ws, "ssh.event")
        assert _next(ws, "alert.updated")["data"]["peak_value"] == 2.0
