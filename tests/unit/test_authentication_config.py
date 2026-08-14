from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from ai_fde.config import Settings


def test_development_identity_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="Development identity is forbidden"):
        Settings(env="production", auth_mode="development")


def test_oidc_mode_is_allowed_in_production_configuration() -> None:
    settings = Settings(
        env="production",
        auth_mode="oidc",
        cockpit_url="https://cockpit.example.com",
        allowed_origins=["https://cockpit.example.com"],
        oidc_issuer_url="https://tenant.us.auth0.com/",
        oidc_client_id="client-id",
        oidc_client_secret=SecretStr("client-secret"),
        oidc_redirect_uri="https://api.example.com/api/auth/callback",
        oidc_allowed_emails=["fde@example.com"],
        worker_operator_id=UUID("00000000-0000-4000-8000-000000000002"),
        extraction_provider="bedrock",
        bedrock_model_id="us.anthropic.claude-test-v1:0",
        s3_endpoint_url=None,
        s3_use_workload_identity=True,
    )

    assert settings.auth_mode == "oidc"


def test_oidc_mode_rejects_missing_provider_configuration() -> None:
    with pytest.raises(ValidationError, match="OIDC authentication requires"):
        Settings(auth_mode="oidc")


def test_production_oidc_rejects_insecure_application_urls() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            env="production",
            auth_mode="oidc",
            oidc_issuer_url="https://tenant.us.auth0.com/",
            oidc_client_id="client-id",
            oidc_client_secret=SecretStr("client-secret"),
            oidc_allowed_emails=["fde@example.com"],
            worker_operator_id=UUID("00000000-0000-4000-8000-000000000002"),
            extraction_provider="bedrock",
            bedrock_model_id="us.anthropic.claude-test-v1:0",
            s3_endpoint_url=None,
            s3_use_workload_identity=True,
        )


def test_sanitized_data_requires_a_production_validation_record() -> None:
    with pytest.raises(ValidationError, match="recorded deployment validation"):
        Settings(
            env="production",
            auth_mode="oidc",
            cockpit_url="https://cockpit.example.com",
            allowed_origins=["https://cockpit.example.com"],
            oidc_issuer_url="https://tenant.us.auth0.com/",
            oidc_client_id="client-id",
            oidc_client_secret=SecretStr("client-secret"),
            oidc_redirect_uri="https://api.example.com/api/auth/callback",
            oidc_allowed_emails=["fde@example.com"],
            worker_operator_id=UUID("00000000-0000-4000-8000-000000000002"),
            extraction_provider="bedrock",
            bedrock_model_id="us.anthropic.claude-test-v1:0",
            s3_endpoint_url=None,
            s3_use_workload_identity=True,
            sanitized_data_enabled=True,
        )


def test_bedrock_worker_lease_must_cover_the_provider_timeout() -> None:
    with pytest.raises(ValidationError, match="lease must exceed"):
        Settings(
            extraction_provider="bedrock",
            bedrock_model_id="us.anthropic.claude-test-v1:0",
            bedrock_read_timeout_seconds=240,
            worker_lease_seconds=240,
        )


def test_production_worker_does_not_require_the_api_oidc_secret() -> None:
    settings = Settings(
        env="production",
        runtime_role="worker",
        auth_mode="oidc",
        cockpit_url="https://cockpit.example.com",
        allowed_origins=["https://cockpit.example.com"],
        oidc_issuer_url="https://tenant.us.auth0.com/",
        oidc_client_id="client-id",
        oidc_redirect_uri="https://api.example.com/api/auth/callback",
        oidc_allowed_emails=["fde@example.com"],
        worker_operator_id=UUID("00000000-0000-4000-8000-000000000002"),
        extraction_provider="bedrock",
        bedrock_model_id="us.anthropic.claude-test-v1:0",
        s3_endpoint_url=None,
        s3_use_workload_identity=True,
    )

    assert settings.oidc_client_secret is None
