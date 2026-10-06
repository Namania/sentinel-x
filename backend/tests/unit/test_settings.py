import pytest
from pydantic import ValidationError

from app.infrastructure.config import Settings


def test_database_url_is_built_from_components():
    settings = Settings(
        _env_file=None,
        postgres_user="u",
        postgres_password="p",
        postgres_db="d",
        postgres_host="h",
        postgres_port=5433,
        jwt_secret="x" * 32,
    )
    assert settings.database_url == "postgresql+asyncpg://u:p@h:5433/d"


def test_defaults_target_compose_db_service():
    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.database_url == "postgresql+asyncpg://sentinel:sentinel@db:5432/sentinel"


def test_rejects_short_or_placeholder_jwt_secret():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="change-me")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="short")


def test_camera_stream_url_is_optional():
    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.camera_stream_url is None
    configured = Settings(
        _env_file=None, jwt_secret="x" * 32, camera_stream_url="http://10.0.0.5:81/stream"
    )
    assert configured.camera_stream_url == "http://10.0.0.5:81/stream"


def test_device_api_key_is_optional_but_must_be_long_when_set():
    assert Settings(_env_file=None, jwt_secret="x" * 32).device_api_key is None
    configured = Settings(_env_file=None, jwt_secret="x" * 32, device_api_key="k" * 16)
    assert configured.device_api_key == "k" * 16
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="x" * 32, device_api_key="short")


def test_empty_device_api_key_means_unset():
    settings = Settings(_env_file=None, jwt_secret="x" * 32, device_api_key="")
    assert settings.device_api_key is None


def test_mqtt_is_optional_with_sane_defaults():
    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.mqtt_host is None
    assert (settings.mqtt_port, settings.mqtt_topic) == (1883, "sentinel/+")
    configured = Settings(_env_file=None, jwt_secret="x" * 32, mqtt_host="mosquitto")
    assert configured.mqtt_host == "mosquitto"
