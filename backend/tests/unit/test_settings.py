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
