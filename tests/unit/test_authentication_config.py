from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from ai_fde.config import Settings
from ai_fde.modules.identity.database import (
    AWS_RDS_TLS_CA_PATH,
    worker_database_user_for_release,
)
from tests.qualification import (
    TEST_EVIDENCE_PUBLIC_KEY_B64_SHA256,
    TEST_EVIDENCE_PUBLIC_KEY_DER_B64,
    build_qualification_record,
)

PRODUCTION_REVISION = "a" * 40
PRODUCTION_DEPLOYMENT = "qualification-test"
PRODUCTION_TLS_QUERY = (
    f"sslmode=verify-full&sslrootcert={AWS_RDS_TLS_CA_PATH}"
)
PRODUCTION_APP_DATABASE_URL = (
    "postgresql+psycopg://ai_fde_app:app-password@"
    f"db.example.us-east-1.rds.amazonaws.com:5432/ai_fde?{PRODUCTION_TLS_QUERY}"
)
PRODUCTION_MIGRATION_DATABASE_URL = (
    "postgresql+psycopg://ai_fde_owner:owner-password@"
    f"db.example.us-east-1.rds.amazonaws.com:5432/ai_fde?{PRODUCTION_TLS_QUERY}"
)
S3_KMS_KEY_ARN = (
    "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789099"
)
QUALIFICATION_SECRET_POLICY_SHA256 = "sha256:" + "7" * 64


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "env": "production",
        "runtime_role": "api",
        "release_revision": PRODUCTION_REVISION,
        "deployment_id": PRODUCTION_DEPLOYMENT,
        "deployment_qualification_mode": "controlled-design-partner",
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
        "database_url": PRODUCTION_APP_DATABASE_URL,
        "migration_database_url": PRODUCTION_MIGRATION_DATABASE_URL,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_development_identity_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="Development identity is forbidden"):
        Settings(env="production", auth_mode="development")


def test_oidc_mode_is_allowed_in_production_configuration() -> None:
    settings = Settings(
        env="production",
        release_revision=PRODUCTION_REVISION,
        deployment_id=PRODUCTION_DEPLOYMENT,
        deployment_qualification_mode="controlled-design-partner",
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
        database_url=PRODUCTION_APP_DATABASE_URL,
        migration_database_url=PRODUCTION_MIGRATION_DATABASE_URL,
    )

    assert settings.auth_mode == "oidc"


def test_production_rejects_an_all_zero_release_revision() -> None:
    with pytest.raises(ValidationError, match="non-placeholder"):
        Settings(
            env="production",
            release_revision="0" * 40,
            deployment_id=PRODUCTION_DEPLOYMENT,
            deployment_qualification_mode="controlled-design-partner",
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


def test_oidc_mode_rejects_missing_provider_configuration() -> None:
    with pytest.raises(ValidationError, match="OIDC authentication requires"):
        Settings(auth_mode="oidc")


def test_production_oidc_rejects_insecure_application_urls() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            env="production",
            release_revision=PRODUCTION_REVISION,
            deployment_id=PRODUCTION_DEPLOYMENT,
            deployment_qualification_mode="controlled-design-partner",
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


def test_sanitized_data_requires_a_production_qualification_record() -> None:
    with pytest.raises(ValidationError, match="immutable deployment qualification record"):
        Settings(
            env="production",
            release_revision=PRODUCTION_REVISION,
            deployment_id=PRODUCTION_DEPLOYMENT,
            deployment_qualification_mode="controlled-design-partner",
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


def test_sanitized_data_requires_one_worker_engagement() -> None:
    with pytest.raises(ValidationError, match="never accepted without"):
        Settings(
            env="production",
            release_revision=PRODUCTION_REVISION,
            deployment_id=PRODUCTION_DEPLOYMENT,
            deployment_qualification_mode="controlled-design-partner",
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
            deployment_validation_id="sha256:" + ("b" * 64),
        )


def test_deployment_validation_id_is_never_accepted_without_its_record() -> None:
    with pytest.raises(ValidationError, match="never accepted without"):
        Settings(deployment_validation_id="anything")


def test_s3_kms_configuration_requires_an_exact_key_arn() -> None:
    assert Settings(s3_kms_key_arn=S3_KMS_KEY_ARN).s3_kms_key_arn == S3_KMS_KEY_ARN

    with pytest.raises(ValidationError, match="exact KMS key ARN"):
        Settings(s3_kms_key_arn="arn:aws:kms:us-east-1:123456789012:alias/evidence")


def test_sanitized_or_production_runtime_cannot_disable_deployment_heartbeats() -> None:
    development_demo = Settings(worker_heartbeat_enabled=False)
    assert development_demo.worker_heartbeat_enabled is False

    with pytest.raises(ValidationError, match="synthetic development demos"):
        Settings(worker_heartbeat_enabled=False, sanitized_data_enabled=True)

    with pytest.raises(ValidationError, match="synthetic development demos"):
        _production_settings(worker_heartbeat_enabled=False)


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
        release_revision=PRODUCTION_REVISION,
        deployment_id=PRODUCTION_DEPLOYMENT,
        deployment_qualification_mode="controlled-design-partner",
        runtime_role="worker",
        database_auth_mode="rds-iam",
        database_url=(
            "postgresql+psycopg://"
            f"{worker_database_user_for_release(PRODUCTION_DEPLOYMENT, PRODUCTION_REVISION)}@"
            "db.example.us-east-1.rds.amazonaws.com:5432/ai_fde?"
            f"{PRODUCTION_TLS_QUERY}"
        ),
        migration_database_url=PRODUCTION_MIGRATION_DATABASE_URL,
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


def test_production_database_urls_require_the_pinned_rds_ca_bundle() -> None:
    with pytest.raises(ValidationError, match="pinned AWS RDS CA bundle"):
        Settings(
            env="production",
            runtime_role="api",
            release_revision=PRODUCTION_REVISION,
            deployment_id=PRODUCTION_DEPLOYMENT,
            deployment_qualification_mode="controlled-design-partner",
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
            database_url=(
                "postgresql+psycopg://ai_fde_app:app-password@"
                "db.example.us-east-1.rds.amazonaws.com:5432/ai_fde?sslmode=verify-full"
            ),
            migration_database_url=PRODUCTION_MIGRATION_DATABASE_URL,
        )


def test_production_api_requires_the_exact_app_database_login() -> None:
    wrong_url = PRODUCTION_APP_DATABASE_URL.replace("ai_fde_app", "ai_fde_owner", 1)

    with pytest.raises(ValidationError, match="exact least-privilege database login"):
        _production_settings(database_url=wrong_url)


def test_production_migration_requires_the_exact_owner_database_login() -> None:
    wrong_url = PRODUCTION_MIGRATION_DATABASE_URL.replace(
        "ai_fde_owner", "ai_fde_app", 1
    )

    with pytest.raises(ValidationError, match="exact least-privilege database login"):
        _production_settings(runtime_role="migration", migration_database_url=wrong_url)


def test_stolen_shared_worker_password_cannot_create_production_readiness() -> None:
    worker_operator_id = UUID("00000000-0000-4000-8000-000000000002")
    worker_engagement_id = UUID("00000000-0000-4000-8000-000000000003")
    qualifier_role_arn = "arn:aws:iam::123456789012:role/ai-fde-qualifier"
    raw_record, version_id = build_qualification_record(
        worker_operator_id=worker_operator_id,
        worker_engagement_id=worker_engagement_id,
        qualifier_role_arn=qualifier_role_arn,
    )

    with pytest.raises(ValidationError, match="requires RDS IAM"):
        Settings(
            env="production",
            release_revision=PRODUCTION_REVISION,
            deployment_id=PRODUCTION_DEPLOYMENT,
            deployment_qualification_mode="controlled-design-partner",
            runtime_role="worker",
            auth_mode="oidc",
            cockpit_url="https://cockpit.example.com",
            allowed_origins=["https://cockpit.example.com"],
            oidc_issuer_url="https://tenant.us.auth0.com/",
            oidc_client_id="client-id",
            oidc_redirect_uri="https://api.example.com/api/auth/callback",
            oidc_allowed_emails=["fde@example.com"],
            worker_operator_id=worker_operator_id,
            worker_engagement_id=worker_engagement_id,
            extraction_provider="bedrock",
            bedrock_model_id="profile-v1",
            s3_endpoint_url=None,
            s3_use_workload_identity=True,
            sanitized_data_enabled=True,
            deployment_qualification_record=SecretStr(raw_record),
            deployment_qualification_record_version_id=version_id,
            deployment_qualification_role_arn=qualifier_role_arn,
            qualification_secret_policy_sha256=QUALIFICATION_SECRET_POLICY_SHA256,
            database_url=(
                "postgresql+psycopg://ai_fde_worker:stolen-shared-password@"
                "db.example.us-east-1.rds.amazonaws.com:5432/ai_fde?sslmode=verify-full"
            ),
            database_auth_mode="password",
        )


def test_validation_id_is_derived_from_the_exact_qualification_version() -> None:
    worker_operator_id = UUID("00000000-0000-4000-8000-000000000002")
    worker_engagement_id = UUID("00000000-0000-4000-8000-000000000003")
    qualifier_role_arn = "arn:aws:iam::123456789012:role/ai-fde-qualifier"
    raw_record, version_id = build_qualification_record()
    settings = Settings(
        env="production",
        release_revision=PRODUCTION_REVISION,
        deployment_id=PRODUCTION_DEPLOYMENT,
        deployment_qualification_mode="controlled-design-partner",
        auth_mode="oidc",
        cockpit_url="https://cockpit.example.com",
        allowed_origins=["https://cockpit.example.com"],
        oidc_issuer_url="https://tenant.us.auth0.com/",
        oidc_client_id="client-id",
        oidc_client_secret=SecretStr("client-secret"),
        oidc_redirect_uri="https://api.example.com/api/auth/callback",
        oidc_allowed_emails=["fde@example.com"],
        worker_operator_id=worker_operator_id,
        worker_engagement_id=worker_engagement_id,
        extraction_provider="bedrock",
        bedrock_model_id="profile-v1",
        s3_endpoint_url=None,
        s3_use_workload_identity=True,
        s3_kms_key_arn=S3_KMS_KEY_ARN,
        sanitized_data_enabled=True,
        deployment_qualification_record=SecretStr(raw_record),
        deployment_qualification_record_version_id=version_id,
        deployment_qualification_role_arn=qualifier_role_arn,
        qualification_secret_policy_sha256=QUALIFICATION_SECRET_POLICY_SHA256,
        evidence_signing_public_key_der_b64=TEST_EVIDENCE_PUBLIC_KEY_DER_B64,
        evidence_signing_public_key_b64_sha256=TEST_EVIDENCE_PUBLIC_KEY_B64_SHA256,
        database_url=PRODUCTION_APP_DATABASE_URL,
        migration_database_url=PRODUCTION_MIGRATION_DATABASE_URL,
    )

    assert settings.deployment_validation_id == f"sha256:{version_id}"

    invalid_values = settings.model_dump()
    invalid_values["s3_kms_key_arn"] = None
    with pytest.raises(ValidationError, match="S3_KMS_KEY_ARN"):
        Settings.model_validate(invalid_values)


def test_production_requires_the_bedrock_extraction_provider() -> None:
    with pytest.raises(ValidationError, match="Production requires the Bedrock"):
        _production_settings(extraction_provider="deterministic")


def test_bedrock_extraction_requires_a_model_identifier() -> None:
    with pytest.raises(ValidationError, match="requires AI_FDE_BEDROCK_MODEL_ID"):
        _production_settings(bedrock_model_id=None)


def test_production_requires_a_dedicated_worker_operator_identity() -> None:
    with pytest.raises(ValidationError, match="requires AI_FDE_WORKER_OPERATOR_ID"):
        _production_settings(worker_operator_id=None)


def test_production_object_storage_requires_workload_identity() -> None:
    with pytest.raises(ValidationError, match="requires the ECS workload identity"):
        _production_settings(s3_use_workload_identity=False)


def test_production_object_storage_rejects_a_custom_endpoint() -> None:
    with pytest.raises(ValidationError, match="must use the regional AWS endpoint"):
        _production_settings(s3_endpoint_url="http://localhost:59000")


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
        _production_settings(oidc_issuer_url="http://tenant.us.auth0.com/")


def test_oidc_allowed_emails_are_normalized_and_deduplicated() -> None:
    settings = _production_settings(
        oidc_allowed_emails=[
            "  FDE@Example.COM ",
            "fde@example.com",
            "second@example.com",
        ]
    )

    assert settings.oidc_allowed_emails == ["fde@example.com", "second@example.com"]


def test_oidc_allowed_emails_that_normalize_to_nothing_are_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one allowed operator email"):
        _production_settings(oidc_allowed_emails=["   ", "\t"])


def test_cockpit_url_must_be_an_allowed_origin() -> None:
    with pytest.raises(ValidationError, match="must be present in the allowed origins"):
        _production_settings(
            allowed_origins=["https://someone-else.example.com"]
        )


def test_allowed_origin_matching_ignores_a_trailing_slash() -> None:
    settings = _production_settings(
        cockpit_url="https://cockpit.example.com/",
        allowed_origins=["https://cockpit.example.com"],
    )

    assert settings.cockpit_url == "https://cockpit.example.com/"
