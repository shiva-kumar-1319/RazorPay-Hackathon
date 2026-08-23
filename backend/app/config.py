"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Database and cache connections are added in later phases."""

    app_name: str = "RecoverX"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://recoverx:recoverx@localhost:5432/recoverx"
    redis_url: str = "redis://localhost:6379/0"
    auto_create_schema: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
