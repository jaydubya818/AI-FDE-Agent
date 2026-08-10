from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, SecretStr, model_validator
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
    cockpit_url: str = "http://localhost:3000"
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_redirect_uri: str = "http://localhost:8000/api/auth/callback"
    oidc_allowed_emails: list[str] = Field(default_factory=list)
    oidc_request_timeout_seconds: int = Field(default=10, ge=2, le=30)
    oidc_login_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    session_cookie_name: str = "ai_fde_session"
    session_ttl_seconds: int = Field(default=43200, ge=900, le=86400)
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
        if self.auth_mode == "oidc":
            required_values = {
                "oidc_issuer_url": self.oidc_issuer_url,
                "oidc_client_id": self.oidc_client_id,
                "oidc_client_secret": self.oidc_client_secret,
                "oidc_allowed_emails": self.oidc_allowed_emails,
            }
            missing = [name for name, value in required_values.items() if not value]
            if missing:
                raise ValueError(f"OIDC authentication requires: {', '.join(missing)}.")
            if not self.oidc_issuer_url or not self.oidc_issuer_url.startswith("https://"):
                raise ValueError("The OIDC issuer URL must use HTTPS.")
            self.oidc_allowed_emails = sorted(
                {email.strip().casefold() for email in self.oidc_allowed_emails if email.strip()}
            )
            if not self.oidc_allowed_emails:
                raise ValueError(
                    "OIDC authentication requires at least one allowed operator email."
                )
            if self.env == "production" and (
                not self.oidc_redirect_uri.startswith("https://")
                or not self.cockpit_url.startswith("https://")
                or any(not origin.startswith("https://") for origin in self.allowed_origins)
            ):
                raise ValueError(
                    "Production OIDC redirect, cockpit, and allowed-origin URLs must use HTTPS."
                )
            normalized_origins = {origin.rstrip("/") for origin in self.allowed_origins}
            if self.cockpit_url.rstrip("/") not in normalized_origins:
                raise ValueError("The cockpit URL must be present in the allowed origins.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
