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


def test_server_health_defaults_point_at_the_container_proc():
    from pathlib import Path

    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.host_proc_path == Path("/proc")
    assert settings.host_thermal_path == Path("/sys/class/thermal")
    assert settings.host_disk_path == Path("/")
    assert settings.server_health_interval_s == 5.0
    assert settings.server_health_enabled is True


def test_server_health_paths_come_from_the_environment(monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("HOST_DISK_PATH", "/host/root")
    monkeypatch.setenv("HOST_THERMAL_PATH", "/host/thermal")
    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.host_disk_path == Path("/host/root")
    assert settings.host_thermal_path == Path("/host/thermal")


def test_alert_thresholds_defaults_and_accessor():
    from app.domain.alert import Thresholds

    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.thresholds() == Thresholds(
        temperature=(10.0, 30.0), humidity=(20.0, 70.0), gas_max=None
    )


def test_alert_thresholds_from_env_and_inverted_bounds_rejected(monkeypatch):
    monkeypatch.setenv("ALERT_TEMPERATURE_MAX_C", "28")
    monkeypatch.setenv("ALERT_GAS_MAX_MV", "1500")
    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.thresholds().temperature == (10.0, 28.0)
    assert settings.thresholds().gas_max == 1500
    monkeypatch.setenv("ALERT_HUMIDITY_MIN_PCT", "80")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="x" * 32)


def test_empty_alert_gas_max_means_disabled(monkeypatch):
    monkeypatch.setenv("ALERT_GAS_MAX_MV", "")
    assert Settings(_env_file=None, jwt_secret="x" * 32).thresholds().gas_max is None


def test_siren_defaults_and_trigger_accessor():
    from app.domain.siren import Trigger

    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.mqtt_buzzer_topic == "sentinel/cmd/buzzer"
    assert settings.buzzer_mute_minutes == 15
    assert settings.triggers() == (
        Trigger("gas", None),
        Trigger("temperature", "high"),
        Trigger("intruder", None),
    )


def test_unknown_buzzer_trigger_is_refused(monkeypatch):
    monkeypatch.setenv("BUZZER_TRIGGERS", "gas,pressure")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="x" * 32)
