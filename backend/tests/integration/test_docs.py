from fastapi.testclient import TestClient

from app.presentation.main import create_app
from tests.integration.conftest import TEST_SETTINGS


def test_swagger_ui_is_served(client):
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text


def test_openapi_lists_auth_routes(client):
    schema = client.get("/openapi.json").json()
    assert {"/auth/login", "/auth/refresh", "/users/me"} <= set(schema["paths"])


def test_root_path_is_used_behind_proxy():
    settings = TEST_SETTINGS.model_copy(update={"api_root_path": "/api"})
    with TestClient(create_app(settings)) as prefixed:
        docs = prefixed.get("/docs")
        schema = prefixed.get("/openapi.json").json()
    assert "/api/openapi.json" in docs.text
    assert schema["servers"] == [{"url": "/api"}]
