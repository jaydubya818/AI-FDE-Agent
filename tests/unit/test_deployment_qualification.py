from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from ai_fde.modules.factory_engineer.canonical import canonical_sha256
from ai_fde.modules.runtime.qualification import (
    DeploymentQualificationError,
    qualification_content_digest,
    readiness_validation_digest,
    validate_deployment_qualification_record,
)
from tests.qualification import (
    TEST_EVIDENCE_PUBLIC_KEY_B64_SHA256,
    TEST_EVIDENCE_PUBLIC_KEY_DER_B64,
    build_qualification_record,
    resign_test_evidence_envelope,
)

WORKER_OPERATOR_ID = UUID("00000000-0000-4000-8000-000000000002")
WORKER_ENGAGEMENT_ID = UUID("00000000-0000-4000-8000-000000000003")
QUALIFIER_ROLE_ARN = "arn:aws:iam::123456789012:role/ai-fde-qualifier"


def _validate(
    raw_record: str,
    version_id: str,
    *,
    now: datetime | None = None,
) -> None:
    validate_deployment_qualification_record(
        raw_record,
        expected_version_id=version_id,
        expected_release_revision="a" * 40,
        expected_deployment_id="qualification-test",
        expected_qualification_mode="controlled-design-partner",
        expected_worker_operator_id=WORKER_OPERATOR_ID,
        expected_worker_engagement_id=WORKER_ENGAGEMENT_ID,
        expected_application_origin="https://cockpit.example.com",
        expected_oidc_issuer_url="https://tenant.us.auth0.com/",
        expected_oidc_client_id="client-id",
        expected_oidc_allowed_emails=["fde@example.com"],
        expected_region="us-east-1",
        expected_qualifier_role_arn=QUALIFIER_ROLE_ARN,
        expected_bedrock_model_id="profile-v1",
        expected_bedrock_classifications=["PUBLIC", "INTERNAL"],
        expected_s3_kms_key_arn=(
            "arn:aws:kms:us-east-1:123456789012:"
            "key/12345678-1234-1234-1234-123456789099"
        ),
        expected_qualification_secret_policy_sha256="sha256:" + "7" * 64,
        expected_evidence_signing_public_key_der_b64=(
            TEST_EVIDENCE_PUBLIC_KEY_DER_B64
        ),
        expected_evidence_signing_public_key_b64_sha256=(
            TEST_EVIDENCE_PUBLIC_KEY_B64_SHA256
        ),
        now=now,
    )


def _rehash(record: dict[str, object]) -> tuple[str, str]:
    record["validation_id"] = readiness_validation_digest(record)
    record["content_digest"] = qualification_content_digest(record)
    return (
        json.dumps(record, sort_keys=True, separators=(",", ":")),
        str(record["validation_id"]).removeprefix("sha256:"),
    )


def _resign_evidence(record: dict[str, Any], label: str) -> None:
    evidence = record["external_evidence"][label]
    envelope = evidence["signed_record"]
    resign_test_evidence_envelope(envelope)
    evidence["content_digest"] = envelope["content_digest"]


def test_exact_immutable_qualification_version_is_accepted() -> None:
    raw_record, version_id = build_qualification_record()
    _validate(raw_record, version_id)


def test_arbitrary_valid_looking_hash_cannot_qualify_a_deployment() -> None:
    raw_record, _version_id = build_qualification_record()

    with pytest.raises(DeploymentQualificationError, match="secret version"):
        _validate(raw_record, "f" * 64)


def test_altered_qualification_record_is_rejected() -> None:
    raw_record, version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["release"]["deployment_id"] = "attacker-deployment"

    with pytest.raises(DeploymentQualificationError, match="deployment_id"):
        _validate(json.dumps(record), version_id)


def test_internally_consistent_record_from_wrong_qualifier_is_rejected() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["aws_principal_arn"] = (
        "arn:aws:sts::123456789012:assumed-role/deployment-role/attacker"
    )
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="dedicated qualifier"):
        _validate(attacker_record, attacker_version)


def test_old_deployment_identity_cannot_replay_qualification() -> None:
    raw_record, version_id = build_qualification_record(
        worker_operator_id=UUID("00000000-0000-4000-8000-000000000099")
    )

    with pytest.raises(DeploymentQualificationError, match="worker_operator_id"):
        _validate(raw_record, version_id)


def test_record_cannot_substitute_another_deployment_database_user() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["release"]["worker_database_user"] = "ai_fde_worker_000000000000"
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="worker_database_user"):
        _validate(attacker_record, attacker_version)


def test_record_cannot_substitute_another_runtime_s3_kms_key() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["checks"]["s3"]["kms_key_arn"] = (
        "arn:aws:kms:us-east-1:123456789012:"
        "key/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="bucket boundary"):
        _validate(attacker_record, attacker_version)


def test_record_cannot_substitute_another_ecs_workload_role() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["release"]["task_role_arns"]["api"] = (
        "arn:aws:iam::123456789012:role/swapped-api-task"
    )
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="not bound to the release roles"):
        _validate(attacker_record, attacker_version)


def test_record_rejects_extra_live_data_role_authority() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["checks"]["ecs_data_role_inventory"]["roles"]["migration_task"][
        "attached_managed_policy_arns"
    ] = ["arn:aws:iam::aws:policy/AdministratorAccess"]
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="migration_task IAM inventory"):
        _validate(attacker_record, attacker_version)


@pytest.mark.parametrize(
    ("check_path", "value", "message"),
    [
        (("rds", "publicly_accessible"), True, "RDS boundary"),
        (("rds", "deletion_protection"), False, "RDS boundary"),
        (("runtime_secrets", "api", "awscurrent_count"), 2, "secret binding"),
        (
            ("runtime_secrets", "api", "current_version_id"),
            "f" * 32,
            "secret binding",
        ),
        (
            (
                "runtime_secrets",
                "api",
                "ecs_value_from",
                "AI_FDE_DATABASE_URL",
            ),
            (
                "arn:aws:secretsmanager:us-east-1:123456789012:"
                "secret:api:AI_FDE_DATABASE_URL::"
            ),
            "secret binding",
        ),
        (
            ("qualification_secret_boundary", "policy_sha256"),
            "sha256:" + "0" * 64,
            "secret",
        ),
        (
            (
                "qualification_control_plane",
                "roles",
                "qualifier",
                "attached_managed_policy_arns",
            ),
            ["arn:aws:iam::aws:policy/AdministratorAccess"],
            "role inventory",
        ),
        (
            (
                "qualification_control_plane",
                "simulations",
                "qualifier_kms_sign",
            ),
            "allowed",
            "simulation matrix",
        ),
    ],
)
def test_runtime_rejects_drifted_live_boundary_claims(
    check_path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    target = record["checks"]
    for key in check_path[:-1]:
        target = target[key]
    target[check_path[-1]] = value
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match=message):
        _validate(attacker_record, attacker_version)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("application_origin", "https://other.example.com"),
        ("oidc_issuer_url", "https://other.us.auth0.com/"),
        ("oidc_client_id", "other-client"),
        ("oidc_allowed_emails", ["attacker@example.com"]),
    ],
)
def test_release_auth_binding_cannot_drift(field: str, value: object) -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["release"][field] = value
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="qualification"):
        _validate(attacker_record, attacker_version)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issuer_url", "https://other.us.auth0.com/"),
        ("callback_url", "https://other.example.com/api/auth/callback"),
    ],
)
def test_signed_auth0_observations_must_match_release_auth_binding(
    field: str,
    value: str,
) -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    results = record["external_evidence"]["auth0"]["signed_record"]["results"]
    results[field] = value
    _resign_evidence(record, "auth0")
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="Auth0 observations"):
        _validate(attacker_record, attacker_version)


def test_prior_worker_identity_claim_must_prove_every_denial() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["checks"]["prior_worker_identity_denials"]["roles"][0][
        "rds_db_connect"
    ] = "allowed"
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="prior-worker denial"):
        _validate(attacker_record, attacker_version)


def test_prior_worker_identity_claim_must_match_the_qualified_account() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["checks"]["prior_worker_identity_denials"]["roles"][0][
        "role_arn"
    ] = "arn:aws:iam::999999999999:role/ai-fde-worker-prior"
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="prior-worker denial"):
        _validate(attacker_record, attacker_version)


def test_standalone_task_drain_rejects_one_running_task() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["checks"]["standalone_task_drain"]["services"]["worker"][
        "running_task_arns"
    ].append(
        "arn:aws:ecs:us-east-1:123456789012:task/ai-fde-design-partner/"
        + "f" * 32
    )
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="standalone-task drain"):
        _validate(attacker_record, attacker_version)


def test_standalone_task_drain_must_match_the_qualified_region_and_account() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["checks"]["standalone_task_drain"]["services"]["worker"][
        "task_definition_arn"
    ] = (
        "arn:aws:ecs:us-west-2:999999999999:"
        "task-definition/ai-fde-worker:42"
    )
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="standalone-task drain"):
        _validate(attacker_record, attacker_version)


def test_external_evidence_summary_cannot_change_its_authenticated_issuer() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["external_evidence"]["auth0"]["issuer_role_arn"] = (
        "arn:aws:iam::123456789012:role/attacker"
    )
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="invalid external evidence"):
        _validate(attacker_record, attacker_version)


def test_external_evidence_summary_requires_the_exact_attestation_mode() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    record["external_evidence"]["auth0"][
        "attestation_mode"
    ] = "machine-verified-kms-attestation"
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="invalid external evidence"):
        _validate(attacker_record, attacker_version)


def test_qualifier_cannot_forge_or_tamper_with_a_signed_evidence_envelope() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    evidence = record["external_evidence"]["auth0"]
    envelope = evidence["signed_record"]
    envelope["results"]["issuer_url"] = "https://attacker.example/"
    attacker_record, attacker_version = _rehash(record)
    with pytest.raises(DeploymentQualificationError, match="digest does not match"):
        _validate(attacker_record, attacker_version)

    unsigned = dict(envelope)
    unsigned.pop("content_digest")
    unsigned.pop("signature")
    forged_digest = canonical_sha256(unsigned)
    envelope["content_digest"] = forged_digest
    envelope["signature"] = base64.b64encode(b"qualifier-forged-signature").decode()
    evidence["content_digest"] = forged_digest
    attacker_record, attacker_version = _rehash(record)
    with pytest.raises(DeploymentQualificationError, match="signature is invalid"):
        _validate(attacker_record, attacker_version)


@pytest.mark.parametrize(
    ("label", "field", "value"),
    [
        ("auth0", "authorization_code_challenge_method", "plain"),
        ("auth0", "allowlisted_callback_status_code", 500),
        ("restore", "digest_matched", False),
        ("deletion", "application_rows_remaining", 1),
        ("secret_rotation", "old_api_login_sqlstate", "00000"),
        ("prior_worker_revocation", "probe_results", {"rds_db_connect": "allowed"}),
    ],
)
def test_correctly_signed_failing_evidence_cannot_qualify_runtime(
    label: str,
    field: str,
    value: object,
) -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    results = record["external_evidence"][label]["signed_record"]["results"]
    if field == "probe_results":
        results["roles"][0]["probe_results"].update(value)
    else:
        results[field] = value
    _resign_evidence(record, label)
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="required outcome"):
        _validate(attacker_record, attacker_version)


def test_correctly_signed_deletion_without_receipt_cannot_qualify_runtime() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    results = record["external_evidence"]["deletion"]["signed_record"]["results"]
    results.pop("deletion_receipt_id")
    _resign_evidence(record, "deletion")
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="strict release contract"):
        _validate(attacker_record, attacker_version)


def test_signed_prior_roles_and_live_denial_claims_must_match_exactly() -> None:
    raw_record, _version_id = build_qualification_record()
    record = json.loads(raw_record)
    denial_check = record["checks"]["prior_worker_identity_denials"]
    denial_check["first_deployment"] = True
    denial_check["roles"] = []
    attacker_record, attacker_version = _rehash(record)

    with pytest.raises(DeploymentQualificationError, match="signed revocation evidence"):
        _validate(attacker_record, attacker_version)


def test_runtime_rejects_a_qualification_record_over_secrets_manager_limit() -> None:
    raw_record, version_id = build_qualification_record()
    oversized = raw_record + (" " * (64 * 1024))

    with pytest.raises(DeploymentQualificationError, match="exceeds the bounded size"):
        _validate(oversized, version_id)


def test_expired_qualification_record_is_rejected() -> None:
    validated_at = datetime.now(UTC) - timedelta(days=2)
    raw_record, version_id = build_qualification_record(now=validated_at)

    with pytest.raises(DeploymentQualificationError, match="expired"):
        _validate(raw_record, version_id)


def test_qualification_record_expires_at_the_exact_boundary() -> None:
    validated_at = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    raw_record, version_id = build_qualification_record(now=validated_at)

    with pytest.raises(DeploymentQualificationError, match="expired"):
        _validate(
            raw_record,
            version_id,
            now=validated_at + timedelta(hours=24),
        )
