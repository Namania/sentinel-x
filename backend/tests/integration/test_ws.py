import pytest
from starlette.websockets import WebSocketDisconnect

from tests.integration.conftest import create_user_and_login


def test_ws_without_token_is_closed_with_1008(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws"):
            pass
    assert exc.value.code == 1008


def test_ws_with_bad_token_is_closed_with_1008(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws?token=garbage"):
            pass
    assert exc.value.code == 1008


def test_ws_with_refresh_token_is_closed_with_1008(client):
    tokens = create_user_and_login(client)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws?token={tokens['refresh_token']}"):
            pass
    assert exc.value.code == 1008


def test_ws_ping_pong(client):
    tokens = create_user_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_ws_echoes_other_messages(client):
    tokens = create_user_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        ws.send_json({"type": "custom", "value": 42})
        assert ws.receive_json() == {"type": "echo", "data": {"type": "custom", "value": 42}}


def test_ws_invalid_json_returns_error_and_keeps_connection(client):
    tokens = create_user_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        ws.send_text("{not json")
        assert ws.receive_json() == {"type": "error", "detail": "invalid json"}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_ws_receives_logged_in_event(client):
    tokens = create_user_and_login(client, email="alice@example.com")
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        create_user_and_login(client, email="bob@example.com")
        event = ws.receive_json()
        assert event["type"] == "user.logged_in"
        assert "user_id" in event


def test_ws_disconnect_removes_connection_from_hub(client, app):
    tokens = create_user_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}"):
        assert app.state.hub.connection_count == 1
    assert app.state.hub.connection_count == 0


def test_ws_binary_frame_returns_error_and_keeps_connection(client):
    tokens = create_user_and_login(client)
    with client.websocket_connect(f"/ws?token={tokens['access_token']}") as ws:
        ws.send_bytes(b"\x00\x01")
        assert ws.receive_json() == {"type": "error", "detail": "expected text frame"}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
