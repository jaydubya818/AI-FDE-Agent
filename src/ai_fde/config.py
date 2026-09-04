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
    runtime_role: Literal["api", "worker", "migration"] = "api"
    auth_mode: Literal["development", "oidc"] = "development"
    database_url: str = "postgresql+psycopg://ai_fde_app:ai_fde_app@localhost:55432/ai_fde"
    migration_database_url: str = (
        "postgresql+psycopg://ai_fde_owner:ai_fde_owner@localhost:55432/ai_fde"
    )
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    operator_id: UUID = UUID("00000000-0000-4000-8000-000000000001")
    operator_subject: str = "local-founder"
    operator_name: str = "Local FDE"
    worker_operator_id: UUID | None = None
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
    s3_endpoint_url: str | None = "http://localhost:59000"
    s3_access_key: str | None = "ai-fde-dev"
    s3_secret_key: SecretStr | None = SecretStr("ai-fde-dev-secret")
    s3_bucket: str = "ai-fde-evidence"
    s3_region: str = "us-east-1"
    s3_use_workload_identity: bool = False
    extraction_provider: Literal["deterministic", "bedrock"] = "deterministic"
    bedrock_model_id: str | None = None
    bedrock_region: str = "us-east-1"
    bedrock_connect_timeout_seconds: int = Field(default=10, ge=2, le=30)
    bedrock_read_timeout_seconds: int = Field(default=240, ge=30, le=600)
    bedrock_max_attempts: int = Field(default=3, ge=1, le=5)
    bedrock_max_output_tokens: int = Field(default=4096, ge=512, le=8192)
    extraction_max_segments_per_job: int = Field(default=100, ge=1, le=1000)
    extraction_max_provider_calls_per_job: int = Field(default=50, ge=1, le=1000)
    extraction_max_provider_tokens_per_job: int = Field(
        default=1_000_000,
        ge=10_000,
        le=10_000_000,
    )
    sanitized_data_enabled: bool = False
    deployment_validation_id: str | None = None
    worker_poll_seconds: float = 1.0
    worker_lease_seconds: int = Field(default=300, ge=30, le=1800)

    @model_validator(mode="after")
    def reject_development_identity_outside_development(self) -> Self:
        if self.env != "development" and self.auth_mode == "development":
            raise ValueError(
                "Development identity is forbidden outside the development environment."
            )
        if self.env == "production" and self.extraction_provider != "bedrock":
            raise ValueError("Production requires the Bedrock extraction provider.")
        if self.extraction_provider == "bedrock" and not self.bedrock_model_id:
            raise ValueError("Bedrock extraction requires AI_FDE_BEDROCK_MODEL_ID.")
        if (
            self.extraction_provider == "bedrock"
            and self.worker_lease_seconds < self.bedrock_read_timeout_seconds + 30
        ):
            raise ValueError(
                "The worker lease must exceed the Bedrock read timeout by at least 30 seconds."
            )
        if self.env == "production":
            if self.worker_operator_id is None:
                raise ValueError("Production requires AI_FDE_WORKER_OPERATOR_ID.")
            if not self.s3_use_workload_identity:
                raise ValueError("Production S3 access requires the ECS workload identity.")
            if self.s3_endpoint_url is not None:
                raise ValueError("Production S3 must use the regional AWS endpoint.")
        if self.sanitized_data_enabled:
            if self.env != "production":
                raise ValueError("Sanitized data can be enabled only in production.")
            if not self.deployment_validation_id or not self.deployment_validation_id.strip():
                raise ValueError(
                    "Sanitized data requires a recorded deployment validation identifier."
                )
        if self.auth_mode == "oidc":
            required_values: dict[str, object] = {
                "oidc_issuer_url": self.oidc_issuer_url,
                "oidc_client_id": self.oidc_client_id,
                "oidc_allowed_emails": self.oidc_allowed_emails,
            }
            if self.runtime_role == "api":
                required_values["oidc_client_secret"] = self.oidc_client_secret
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
