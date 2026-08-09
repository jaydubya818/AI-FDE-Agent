from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_FDE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["development", "oidc"] = "development"
    database_url: str = "postgresql+psycopg://ai_fde_app:ai_fde_app@localhost:55432/ai_fde"
    migration_database_url: str = (
        "postgresql+psycopg://ai_fde_owner:ai_fde_owner@localhost:55432/ai_fde"
    )
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    operator_id: UUID = UUID("00000000-0000-4000-8000-000000000001")
    operator_subject: str = "local-founder"
    operator_name: str = "Local FDE"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    s3_endpoint_url: str = "http://localhost:59000"
    s3_access_key: str = "ai-fde-dev"
    s3_secret_key: str = "ai-fde-dev-secret"
    s3_bucket: str = "ai-fde-evidence"
    s3_region: str = "us-east-1"
    worker_poll_seconds: float = 1.0
    worker_lease_seconds: int = 30

    @model_validator(mode="after")
    def reject_development_identity_outside_development(self) -> Self:
        if self.env != "development" and self.auth_mode == "development":
            raise ValueError(
                "Development identity is forbidden outside the development environment."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
