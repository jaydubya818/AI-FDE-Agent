from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from ai_fde.modules.identity.database import (
    AWS_RDS_TLS_CA_PATH,
    worker_database_user_for_release,
)
from ai_fde.modules.runtime.qualification import (
    VerifiedDeploymentQualification,
    validate_deployment_qualification_record,
)

BedrockDataClassification = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL"]


def _default_bedrock_data_classifications() -> list[BedrockDataClassification]:
    return ["PUBLIC", "INTERNAL"]


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
    release_revision: str = "development"
    deployment_id: str = "local-development"
    deployment_qualification_mode: Literal[
        "development", "controlled-design-partner"
    ] = "development"
    database_url: str = "postgresql+psycopg://ai_fde_app:ai_fde_app@localhost:55432/ai_fde"
    database_auth_mode: Literal["password", "rds-iam"] = "password"
    migration_database_url: str = (
        "postgresql+psycopg://ai_fde_owner:ai_fde_owner@localhost:55432/ai_fde"
    )
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    operator_id: UUID = UUID("00000000-0000-4000-8000-000000000001")
    operator_subject: str = "local-founder"
    operator_name: str = "Local FDE"
    worker_operator_id: UUID | None = None
    worker_engagement_id: UUID | None = None
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
    s3_kms_key_arn: str | None = None
    extraction_provider: Literal["deterministic", "bedrock"] = "deterministic"
    bedrock_model_id: str | None = None
    bedrock_region: str = "us-east-1"
    bedrock_connect_timeout_seconds: int = Field(default=10, ge=2, le=30)
    bedrock_read_timeout_seconds: int = Field(default=240, ge=30, le=600)
    bedrock_max_attempts: int = Field(default=3, ge=1, le=5)
    bedrock_max_output_tokens: int = Field(default=4096, ge=512, le=8192)
    bedrock_allowed_data_classifications: list[BedrockDataClassification] = Field(
        default_factory=_default_bedrock_data_classifications
    )
    extraction_max_segments_per_job: int = Field(default=100, ge=1, le=1000)
    extraction_max_provider_calls_per_job: int = Field(default=50, ge=1, le=1000)
    extraction_max_provider_tokens_per_job: int = Field(
        default=1_000_000,
        ge=10_000,
        le=10_000_000,
    )
    sanitized_data_enabled: bool = False
    deployment_validation_id: str | None = None
    deployment_qualification_record: SecretStr | None = None
    deployment_qualification_record_version_id: str | None = None
    deployment_qualification_role_arn: str | None = None
    qualification_secret_policy_sha256: str | None = None
    evidence_signing_public_key_der_b64: str | None = None
    evidence_signing_public_key_b64_sha256: str | None = None
    factory_engineer_issuer_id: str = Field(
        default="factory-engineer",
        min_length=1,
        max_length=255,
    )
    worker_poll_seconds: float = 1.0
    worker_lease_seconds: int = Field(default=300, ge=30, le=1800)
    worker_heartbeat_enabled: bool = True
    worker_heartbeat_interval_seconds: int = Field(default=15, ge=5, le=120)
    worker_heartbeat_max_age_seconds: int = Field(default=90, ge=30, le=600)
    readiness_queue_max_age_seconds: int = Field(default=600, ge=60, le=3600)

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
        self.bedrock_allowed_data_classifications = sorted(
            set(self.bedrock_allowed_data_classifications)
        )
        if self.extraction_provider == "bedrock" and not self.bedrock_allowed_data_classifications:
            raise ValueError(
                "Bedrock extraction requires at least one allowed data classification."
            )
        if (
            self.extraction_provider == "bedrock"
            and self.worker_lease_seconds < self.bedrock_read_timeout_seconds + 30
        ):
            raise ValueError(
                "The worker lease must exceed the Bedrock read timeout by at least 30 seconds."
            )
        if self.env == "production":
            if not re.fullmatch(r"[0-9a-f]{40}", self.release_revision) or set(
                self.release_revision
            ) == {"0"}:
                raise ValueError(
                    "Production requires AI_FDE_RELEASE_REVISION as a non-placeholder exact "
                    "lowercase Git SHA."
                )
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{7,119}", self.deployment_id):
                raise ValueError(
                    "Production requires a bounded AI_FDE_DEPLOYMENT_ID."
                )
            if self.deployment_qualification_mode != "controlled-design-partner":
                raise ValueError(
                    "Production requires controlled-design-partner qualification mode."
                )
            if self.worker_operator_id is None:
                raise ValueError("Production requires AI_FDE_WORKER_OPERATOR_ID.")
            if self.worker_operator_id.int == 0:
                raise ValueError("Production rejects an all-zero worker operator ID.")
            if self.runtime_role == "worker":
                if self.database_auth_mode != "rds-iam":
                    raise ValueError(
                        "The production worker requires RDS IAM database authentication."
                    )
                worker_database_url = make_url(self.database_url)
                expected_worker_database_user = worker_database_user_for_release(
                    self.deployment_id, self.release_revision
                )
                if (
                    worker_database_url.username != expected_worker_database_user
                    or worker_database_url.password is not None
                    or not worker_database_url.host
                    or worker_database_url.query.get("sslmode") != "verify-full"
                ):
                    raise ValueError(
                        "The production worker database URL must use the passwordless "
                        "release-scoped worker login and sslmode=verify-full."
                    )
            if not self.s3_use_workload_identity:
                raise ValueError("Production S3 access requires the ECS workload identity.")
            if self.s3_endpoint_url is not None:
                raise ValueError("Production S3 must use the regional AWS endpoint.")
        if self.s3_kms_key_arn is not None and not re.fullmatch(
            r"arn:[a-z0-9-]+:kms:[a-z0-9-]+:[0-9]{12}:key/[A-Za-z0-9-]{16,128}",
            self.s3_kms_key_arn,
        ):
            raise ValueError(
                "AI_FDE_S3_KMS_KEY_ARN must be an exact KMS key ARN, not an alias."
            )
        if (
            self.deployment_validation_id is not None
            and self.deployment_qualification_record is None
        ):
            raise ValueError(
                "A deployment validation ID is never accepted without its immutable "
                "qualification record."
            )
        if (self.deployment_qualification_record is None) != (
            self.deployment_qualification_record_version_id is None
        ):
            raise ValueError(
                "The deployment qualification record and exact secret version are both required."
            )
        if self.deployment_qualification_record is not None:
            if self.deployment_qualification_role_arn is None:
                raise ValueError(
                    "A deployment qualification record requires its dedicated qualifier role."
                )
            if not self.qualification_secret_policy_sha256 or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", self.qualification_secret_policy_sha256
            ):
                raise ValueError(
                    "A deployment qualification record requires the exact qualification "
                    "secret policy digest."
                )
            if (
                self.evidence_signing_public_key_der_b64 is None
                or self.evidence_signing_public_key_b64_sha256 is None
            ):
                raise ValueError(
                    "A deployment qualification record requires the pinned evidence public key."
                )
            if self.worker_operator_id is None or self.worker_engagement_id is None:
                raise ValueError(
                    "A deployment qualification record requires the exact worker identity."
                )
            if self.s3_kms_key_arn is None:
                raise ValueError(
                    "A deployment qualification record requires AI_FDE_S3_KMS_KEY_ARN."
                )
            qualification = self.verified_deployment_qualification()
            if (
                self.deployment_validation_id is not None
                and self.deployment_validation_id != qualification.validation_id
            ):
                raise ValueError(
                    "The configured deployment validation ID does not match the immutable record."
                )
            self.deployment_validation_id = qualification.validation_id
        if not self.worker_heartbeat_enabled and (
            self.env != "development" or self.sanitized_data_enabled
        ):
            raise ValueError(
                "Deployment heartbeats can be disabled only for synthetic development demos."
            )
        if self.sanitized_data_enabled:
            if self.env != "production":
                raise ValueError("Sanitized data can be enabled only in production.")
            if self.deployment_qualification_record is None:
                raise ValueError(
                    "Sanitized data requires an immutable deployment qualification record."
                )
            if self.deployment_qualification_mode != "controlled-design-partner":
                raise ValueError(
                    "Sanitized data requires controlled-design-partner qualification mode."
                )
            if self.worker_engagement_id is None or self.worker_engagement_id.int == 0:
                raise ValueError(
                    "Sanitized data requires one non-placeholder worker engagement ID."
                )
            if self.s3_kms_key_arn is None:
                raise ValueError(
                    "Sanitized data requires AI_FDE_S3_KMS_KEY_ARN for explicit SSE-KMS."
                )
        if (
            self.deployment_qualification_mode == "controlled-design-partner"
            and self.env != "production"
        ):
            raise ValueError(
                "Controlled design-partner qualification mode is production-only."
            )
        if self.worker_heartbeat_interval_seconds * 2 >= self.worker_heartbeat_max_age_seconds:
            raise ValueError(
                "The worker heartbeat maximum age must exceed two heartbeat intervals."
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
        if self.env == "production":
            if self.runtime_role == "migration":
                field_name = "AI_FDE_MIGRATION_DATABASE_URL"
                configured_url = self.migration_database_url
                expected_username = "ai_fde_owner"
                requires_password = True
            elif self.runtime_role == "worker":
                field_name = "AI_FDE_DATABASE_URL"
                configured_url = self.database_url
                expected_username = worker_database_user_for_release(
                    self.deployment_id, self.release_revision
                )
                requires_password = False
            else:
                field_name = "AI_FDE_DATABASE_URL"
                configured_url = self.database_url
                expected_username = "ai_fde_app"
                requires_password = True
            database_url = make_url(configured_url)
            if (
                not database_url.host
                or database_url.query.get("sslmode") != "verify-full"
                or database_url.query.get("sslrootcert") != AWS_RDS_TLS_CA_PATH
            ):
                raise ValueError(
                    f"Production {field_name} must use sslmode=verify-full and the "
                    "pinned AWS RDS CA bundle."
                )
            if database_url.username != expected_username or (
                requires_password
                and (not isinstance(database_url.password, str) or not database_url.password)
            ):
                raise ValueError(
                    f"Production {field_name} must use the exact least-privilege database "
                    "login and required authentication material."
                )
        return self

    def verified_deployment_qualification(
        self,
        *,
        now: datetime | None = None,
    ) -> VerifiedDeploymentQualification:
        if (
            self.deployment_qualification_record is None
            or self.deployment_qualification_record_version_id is None
            or self.worker_operator_id is None
            or self.worker_engagement_id is None
        ):
            raise ValueError("The immutable deployment qualification record is unavailable.")
        return validate_deployment_qualification_record(
            self.deployment_qualification_record.get_secret_value(),
            expected_version_id=self.deployment_qualification_record_version_id,
            expected_release_revision=self.release_revision,
            expected_deployment_id=self.deployment_id,
            expected_qualification_mode=self.deployment_qualification_mode,
            expected_worker_operator_id=self.worker_operator_id,
            expected_worker_engagement_id=self.worker_engagement_id,
            expected_application_origin=self.cockpit_url.rstrip("/"),
            expected_oidc_issuer_url=self.oidc_issuer_url or "",
            expected_oidc_client_id=self.oidc_client_id or "",
            expected_oidc_allowed_emails=self.oidc_allowed_emails,
            expected_region=self.s3_region,
            expected_qualifier_role_arn=self.deployment_qualification_role_arn or "",
            expected_bedrock_model_id=self.bedrock_model_id or "",
            expected_bedrock_classifications=self.bedrock_allowed_data_classifications,
            expected_s3_kms_key_arn=self.s3_kms_key_arn or "",
            expected_qualification_secret_policy_sha256=(
                self.qualification_secret_policy_sha256 or ""
            ),
            expected_evidence_signing_public_key_der_b64=(
                self.evidence_signing_public_key_der_b64 or ""
            ),
            expected_evidence_signing_public_key_b64_sha256=(
                self.evidence_signing_public_key_b64_sha256 or ""
            ),
            now=now,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
