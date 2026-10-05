from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
