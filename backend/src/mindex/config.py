"""Typed application settings loaded from environment / `.env` (NF3: secrets live in .env)."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "change-me"  # noqa: S105 (development placeholder, refused in production)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MINDEX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: str = "postgresql+psycopg://mindex:mindex@127.0.0.1:5432/mindex"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    jwt_ttl_minutes: int = Field(default=60, gt=0)

    llm_base_url: str = "http://localhost:8080/v1"
    llm_model: str = "qwen3.5-9b-q4_k_m"
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=2)  # proposal: <= 2 (attempts 1-3)

    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"

    @model_validator(mode="after")
    def _strong_secret_outside_development(self) -> Self:
        # NF3: the public placeholder may only sign tokens on a developer's own machine
        # (`development` is the default and what .env.example ships). A `test` deployment
        # (CI, staging) must set its own key; production also needs 32+ characters.
        secret = self.jwt_secret.get_secret_value()
        if self.env != "development" and secret == DEV_JWT_SECRET:
            raise ValueError("MINDEX_JWT_SECRET must not be the development placeholder")
        if self.env == "production" and len(secret) < 32:
            raise ValueError("MINDEX_JWT_SECRET must be set to a random value of 32+ characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
