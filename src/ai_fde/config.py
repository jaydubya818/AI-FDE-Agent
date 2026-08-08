from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_FDE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    database_url: str = "postgresql+psycopg://ai_fde_app:ai_fde_app@localhost:55432/ai_fde"
    migration_database_url: str = (
        "postgresql+psycopg://ai_fde_owner:ai_fde_owner@localhost:55432/ai_fde"
    )
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
