from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.alert import Thresholds
from app.domain.siren import Trigger, parse_triggers


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "sentinel"
    postgres_password: str = "sentinel"
    postgres_db: str = "sentinel"
    postgres_host: str = "db"
    postgres_port: int = 5432

    api_root_path: str = ""

    # MJPEG stream of the ESP32 camera, e.g. http://192.168.1.50:81/stream
    camera_stream_url: str | None = None

    # Person detection (YOLOv8n, ONNX through OpenCV) against the relayed camera stream.
    vision_enabled: bool = False
    vision_interval_seconds: float = 1.0
    # Whether to also identify each detected person against the known-faces whitelist
    # (YuNet + SFace, ONNX through OpenCV).
    vision_identify_faces: bool = False
    vision_known_faces_dir: str = "data/known_faces"
    # Where the ONNX models are; the Docker image puts them in /app/models at build time.
    vision_models_dir: str = "models"
    # CPU cores the models may use: leave some for the rest of the Pi (video, API, database).
    vision_threads: int = 2

    # Shared secret the ESP32 devices send in X-Device-Key to post sensor readings.
    device_api_key: str | None = None

    # MQTT broker the ESP32 devices publish to; unset → no subscriber is started.
    mqtt_host: str | None = None
    mqtt_port: int = 1883
    mqtt_topic: str = "sentinel/+"

    # Host health shown on the dashboard. /proc inside Docker already describes the host; the
    # thermal zone and the disk are bind-mounted by compose.yml (see HOST_* there).
    host_proc_path: Path = Path("/proc")
    host_thermal_path: Path = Path("/sys/class/thermal")
    host_disk_path: Path = Path("/")
    server_health_interval_s: float = 5.0
    server_health_enabled: bool = True

    # Sensor alert bounds, the same for every device; a reading outside opens an alert.
    alert_temperature_min_c: float = 10.0
    alert_temperature_max_c: float = 30.0
    alert_humidity_min_pct: float = 20.0
    alert_humidity_max_pct: float = 70.0
    alert_gas_max_mv: int | None = None  # None → only the device's own gas alert flag counts

    # Siren: the ESP32 buzzer follows a retained MQTT state message (see docs/.../siren spec).
    mqtt_buzzer_topic: str = "sentinel/cmd/buzzer"
    # "metric" or "metric:low|high", comma-separated.
    buzzer_triggers: str = "gas,temperature:high,intruder"
    buzzer_mute_minutes: int = Field(default=15, ge=1, le=240)

    def triggers(self) -> tuple[Trigger, ...]:
        return parse_triggers(self.buzzer_triggers)

    def thresholds(self) -> Thresholds:
        return Thresholds(
            temperature=(self.alert_temperature_min_c, self.alert_temperature_max_c),
            humidity=(self.alert_humidity_min_pct, self.alert_humidity_max_pct),
            gas_max=self.alert_gas_max_mv,
        )

    @field_validator("alert_gas_max_mv", mode="before")
    @classmethod
    def _empty_gas_max_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def _alert_bounds_must_be_ordered(self) -> "Settings":
        self.thresholds()  # raises ValueError on min >= max → ValidationError
        self.triggers()  # raises ValueError on an unknown metric or direction
        return self

    @field_validator("device_api_key")
    @classmethod
    def _device_key_must_be_long(cls, value: str | None) -> str | None:
        if not value:  # "" (an empty line in .env) means "not configured"
            return None
        if len(value) < 16:
            raise ValueError("DEVICE_API_KEY must be at least 16 characters")
        return value

    jwt_secret: str
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 604800

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_must_be_strong(cls, value: str) -> str:
        if len(value) < 32 or value == "change-me":
            raise ValueError("JWT_SECRET must be at least 32 characters and not a placeholder")
        return value

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
