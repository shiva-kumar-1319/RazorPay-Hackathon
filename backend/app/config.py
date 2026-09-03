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
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    # Gateway & Secrets Configuration
    use_live_gateway: bool = False
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    use_llm_explanations: bool = False
    gemini_api_key: str | None = None
    merchant_api_keys: dict[str, str] = {}


    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                return json.loads(value)
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @field_validator("merchant_api_keys", mode="before")
    @classmethod
    def parse_merchant_api_keys(cls, value: Any) -> dict[str, str]:
        if isinstance(value, str):
            val = value.strip()
            if val.startswith("{") and val.endswith("}"):
                return json.loads(val)
            pairs: dict[str, str] = {}
            for item in val.split(","):
                if ":" in item:
                    k, v = item.split(":", 1)
                    pairs[k.strip()] = v.strip()
            return pairs
        return value or {}

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
