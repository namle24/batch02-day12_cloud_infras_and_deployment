"""Application settings loaded from environment variables."""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "0.0.0.0"
    port: int = Field(default=8000, validation_alias="PORT")
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    app_name: str = "Day 12 Production AI Agent"
    app_version: str = "1.0.0"
    llm_model: str = "mock-llm"

    agent_api_key: str = Field(default="dev-key-change-me", min_length=8)
    allowed_origins: str = "*"

    redis_url: str = "redis://localhost:6379/0"
    rate_limit_per_minute: int = 10
    monthly_budget_usd: float = 10.0
    history_ttl_seconds: int = 60 * 60 * 24 * 30
    max_history_messages: int = 20

    input_price_per_1k_tokens: float = 0.00015
    output_price_per_1k_tokens: float = 0.00060

    @property
    def cors_origins(self) -> list[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
