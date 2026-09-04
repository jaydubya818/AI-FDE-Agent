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


def _production_kwargs(**overrides: object) -> dict[str, object]:
    """Baseline settings that pass every production validator."""
    base: dict[str, object] = {
        "env": "production",
        "auth_mode": "oidc",
        "cockpit_url": "https://cockpit.example.com",
        "allowed_origins": ["https://cockpit.example.com"],
        "oidc_issuer_url": "https://tenant.us.auth0.com/",
        "oidc_client_id": "client-id",
        "oidc_client_secret": SecretStr("client-secret"),
        "oidc_redirect_uri": "https://api.example.com/api/auth/callback",
        "oidc_allowed_emails": ["fde@example.com"],
        "worker_operator_id": UUID("00000000-0000-4000-8000-000000000002"),
        "extraction_provider": "bedrock",
        "bedrock_model_id": "us.anthropic.claude-test-v1:0",
        "s3_endpoint_url": None,
        "s3_use_workload_identity": True,
    }
    base.update(overrides)
    return base


def test_production_requires_the_bedrock_extraction_provider() -> None:
    with pytest.raises(ValidationError, match="Production requires the Bedrock"):
        Settings.model_validate(_production_kwargs(extraction_provider="deterministic"))


def test_bedrock_extraction_requires_a_model_identifier() -> None:
    with pytest.raises(ValidationError, match="requires AI_FDE_BEDROCK_MODEL_ID"):
        Settings.model_validate(_production_kwargs(bedrock_model_id=None))


def test_production_requires_a_dedicated_worker_operator_identity() -> None:
    with pytest.raises(ValidationError, match="requires AI_FDE_WORKER_OPERATOR_ID"):
        Settings.model_validate(_production_kwargs(worker_operator_id=None))


def test_production_object_storage_requires_workload_identity() -> None:
    with pytest.raises(ValidationError, match="requires the ECS workload identity"):
        Settings.model_validate(_production_kwargs(s3_use_workload_identity=False))


def test_production_object_storage_rejects_a_custom_endpoint() -> None:
    with pytest.raises(ValidationError, match="must use the regional AWS endpoint"):
        Settings.model_validate(
            _production_kwargs(s3_endpoint_url="http://localhost:59000")
        )


def test_sanitized_data_cannot_be_enabled_outside_production() -> None:
    with pytest.raises(ValidationError, match="only in production"):
        Settings(
            env="test",
            auth_mode="oidc",
            cockpit_url="https://cockpit.example.com",
            allowed_origins=["https://cockpit.example.com"],
            oidc_issuer_url="https://tenant.us.auth0.com/",
            oidc_client_id="client-id",
            oidc_client_secret=SecretStr("client-secret"),
            oidc_allowed_emails=["fde@example.com"],
            sanitized_data_enabled=True,
        )


def test_oidc_issuer_url_must_use_https() -> None:
    with pytest.raises(ValidationError, match="issuer URL must use HTTPS"):
        Settings.model_validate(
            _production_kwargs(oidc_issuer_url="http://tenant.us.auth0.com/")
        )


def test_oidc_allowed_emails_are_normalized_and_deduplicated() -> None:
    settings = Settings.model_validate(
        _production_kwargs(
            oidc_allowed_emails=["  FDE@Example.COM ", "fde@example.com", "second@example.com"]
        )
    )

    assert settings.oidc_allowed_emails == ["fde@example.com", "second@example.com"]


def test_oidc_allowed_emails_that_normalize_to_nothing_are_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one allowed operator email"):
        Settings.model_validate(_production_kwargs(oidc_allowed_emails=["   ", "\t"]))


def test_cockpit_url_must_be_an_allowed_origin() -> None:
    with pytest.raises(ValidationError, match="must be present in the allowed origins"):
        Settings.model_validate(
            _production_kwargs(allowed_origins=["https://someone-else.example.com"])
        )


def test_allowed_origin_matching_ignores_a_trailing_slash() -> None:
    settings = Settings.model_validate(
        _production_kwargs(
            cockpit_url="https://cockpit.example.com/",
            allowed_origins=["https://cockpit.example.com"],
        )
    )

    assert settings.cockpit_url == "https://cockpit.example.com/"
