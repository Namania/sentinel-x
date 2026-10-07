import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.infrastructure.camera.relay import CameraRelay
from app.presentation.main import create_app
from tests.integration.conftest import TEST_SETTINGS, create_user_and_login
from tests.unit.fakes import FakeCamera


def test_stream_requires_a_token(client):
    response = client.get("/camera/stream")
    assert response.status_code == 401


def test_stream_rejects_a_refresh_token(client):
    tokens = create_user_and_login(client)
    response = client.get(f"/camera/stream?token={tokens['refresh_token']}")
    assert response.status_code == 401


def test_stream_is_unavailable_when_no_camera_is_configured(client):
    tokens = create_user_and_login(client)
    response = client.get(f"/camera/stream?token={tokens['access_token']}")
    assert response.status_code == 503


def test_openapi_lists_camera_stream(client):
    schema = client.get("/openapi.json").json()
    assert "/camera/stream" in schema["paths"]


@pytest.fixture
def camera() -> FakeCamera:
    camera = FakeCamera()
    camera.push_frame(b"\xff\xd8first\xff\xd9")
    camera.push_frame(b"\xff\xd8second\xff\xd9")
    return camera


@pytest.fixture
def live_server(camera: FakeCamera) -> Iterator[str]:
    """A real uvicorn server, needed because TestClient buffers whole responses."""
    settings = TEST_SETTINGS.model_copy(update={"camera_stream_url": "http://cam.local:81/stream"})
    app = create_app(settings)
    app.state.camera_relay = CameraRelay(camera.open, retry_delay=0.01)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def read_first_frames(response: httpx.Response, count: int) -> bytes:
    received = b""
    for chunk in response.iter_bytes():
        received += chunk
        if received.count(b"\xff\xd9") >= count:
            return received
    raise AssertionError(f"stream ended early: {received!r}")


def test_stream_relays_camera_frames_as_mjpeg(client, live_server, camera):
    tokens = create_user_and_login(client)
    with httpx.Client(timeout=5) as http:
        with http.stream("GET", f"{live_server}/camera/stream?token={tokens['access_token']}") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("multipart/x-mixed-replace; boundary=")
            assert r.headers["cache-control"] == "no-store"
            boundary = r.headers["content-type"].split("boundary=")[1]
            body = read_first_frames(r, 1)
    assert f"--{boundary}\r\n".encode() in body
    assert b"Content-Type: image/jpeg\r\n" in body
    assert b"\xff\xd8second\xff\xd9" in body or b"\xff\xd8first\xff\xd9" in body


def test_stream_accepts_bearer_header(client, live_server):
    tokens = create_user_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    with httpx.Client(timeout=5) as http:
        with http.stream("GET", f"{live_server}/camera/stream", headers=headers) as r:
            assert r.status_code == 200
            read_first_frames(r, 1)


def test_camera_is_released_when_viewers_disconnect(client, live_server, camera):
    tokens = create_user_and_login(client)
    with httpx.Client(timeout=5) as http:
        with http.stream("GET", f"{live_server}/camera/stream?token={tokens['access_token']}") as r:
            read_first_frames(r, 1)
    deadline = time.monotonic() + 5
    while camera.closes == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert camera.opens == 1
    assert camera.closes == 1


def test_status_requires_a_token(client):
    assert client.get("/camera/status").status_code == 401


def test_status_reports_an_unconfigured_camera(client):
    tokens = create_user_and_login(client)
    response = client.get(f"/camera/status?token={tokens['access_token']}")
    assert response.status_code == 200
    assert response.json() == {"configured": False, "viewers": 0, "frames": 0}


def test_status_reports_a_configured_camera_and_its_viewers(client):
    tokens = create_user_and_login(client)
    app = create_app(TEST_SETTINGS)
    app.state.camera_relay = CameraRelay(FakeCamera().open, retry_delay=0.01)
    with TestClient(app) as configured:
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        response = configured.get("/camera/status", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"configured": True, "viewers": 0, "frames": 0}
