"""Application configuration loaded from environment variables."""

import json
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the RecoverX application."""

    app_name: str = "RecoverX"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    log_format: str = "text"  # "text" or "json"
    database_url: str = "postgresql+psycopg://recoverx:recoverx@localhost:5432/recoverx"
    redis_url: str = "redis://localhost:6379/0"
    auto_create_schema: bool = False
    run_migrations: bool = False
    cors_origins: list[str] = ["*"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                return json.loads(value)
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
