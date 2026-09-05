from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils

from ai_fde.modules.factory_engineer.canonical import canonical_sha256
from ai_fde.modules.identity.database import (
    WORKER_DATABASE_USER_PATTERN,
    worker_database_user_for_release,
)
from ai_fde.modules.runtime.evidence_semantics import (
    EvidenceSemanticsError,
    validate_evidence_results,
)

QUALIFICATION_SCHEMA_VERSION = "design-partner-readiness-v5"
MAX_QUALIFICATION_RECORD_BYTES = 64 * 1024

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_VERSION_ID = re.compile(r"[0-9a-f]{64}")
_SECRET_VERSION_ID = re.compile(r"[A-Za-z0-9-]{32,64}")
_RELEASE_REVISION = re.compile(r"[0-9a-f]{40}")
_DEPLOYMENT_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,119}")
_BOUNDED_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+=,@-]{0,255}")
_ACCOUNT_ID = re.compile(r"[0-9]{12}")
_IAM_ROLE_ARN = re.compile(
    r"arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):iam::([0-9]{12}):role/([A-Za-z0-9+=,.@_/-]+)"
)
_ROLE_ARN = re.compile(
    r"arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):sts::([0-9]{12}):"
    r"assumed-role/([A-Za-z0-9+=,.@_/-]+)"
)
_IMAGE = re.compile(r".+@sha256:[0-9a-f]{64}")
_REGION = re.compile(r"[a-z]{2}(?:-gov)?-[a-z]+-[0-9]")
_BEDROCK_ARN = re.compile(
    r"arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):bedrock:([a-z0-9-]{1,20}):"
    r":foundation-model/([A-Za-z0-9:.-]+)"
)
_OIDC_CLIENT_ID = re.compile(r"[A-Za-z0-9._~-]{3,255}")
_EMAIL = re.compile(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,63}")
_KMS_KEY_ARN = re.compile(
    r"arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):kms:([a-z0-9-]{1,20}):"
    r"([0-9]{12}):key/([A-Za-z0-9-]{8,128})"
)
_SECRET_ARN = re.compile(
    r"arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):secretsmanager:([a-z0-9-]{1,20}):"
    r"([0-9]{12}):secret:[A-Za-z0-9/_+=.@-]{1,512}"
)
_RDS_DB_USER_ARN = re.compile(
    r"arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):rds-db:([a-z0-9-]{1,20}):"
    r"([0-9]{12}):dbuser/([A-Za-z0-9-]{8,128})/(ai_fde_worker_[0-9a-f]{12})"
)
_TASK_DEFINITION_ARN = re.compile(
    r"arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):ecs:([a-z0-9-]{1,20}):"
    r"([0-9]{12}):task-definition/([A-Za-z0-9_-]{1,255}):([1-9][0-9]*)"
)
_TASK_ARN = re.compile(
    r"arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):ecs:([a-z0-9-]{1,20}):"
    r"([0-9]{12}):task/([A-Za-z0-9_-]{1,255})/([0-9a-f]{32})"
)

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "validated_at",
        "expires_at",
        "aws_account_id",
        "aws_principal_arn",
        "region",
        "status",
        "release",
        "external_evidence",
        "checks",
        "validation_id",
        "content_digest",
    }
)
_RELEASE_KEYS = frozenset(
    {
        "git_commit",
        "deployment_id",
        "qualification_mode",
        "worker_operator_id",
        "worker_engagement_id",
        "worker_database_user",
        "application_origin",
        "oidc_issuer_url",
        "oidc_client_id",
        "oidc_allowed_emails",
        "evidence_issuer_role_arn",
        "evidence_signing_key_arn",
        "evidence_signing_public_key_der_b64",
        "evidence_signing_public_key_b64_sha256",
        "bedrock_model_id",
        "bedrock_model_arn",
        "bedrock_allowed_data_classifications",
        "images",
        "task_role_arns",
        "execution_role_arns",
    }
)
_EXTERNAL_EVIDENCE_KEYS = frozenset(
    {"auth0", "restore", "deletion", "secret_rotation", "prior_worker_revocation"}
)
_CHECK_KEYS = frozenset(
    {
        "https",
        "s3",
        "rds",
        "ecs",
        "worker_network",
        "worker_s3_isolation",
        "worker_bedrock_isolation",
        "worker_database_identity",
        "bedrock_logging",
        "bedrock_evaluation",
        "runtime_secrets",
        "qualification_secret_boundary",
        "qualification_control_plane",
        "ecs_data_role_inventory",
        "prior_worker_identity_denials",
        "standalone_task_drain",
    }
)

_EXTERNAL_EVIDENCE_CONTRACT = {
    "auth0": (
        "auth0-live-validation",
        "scripts.seal_auth0_observations",
        "trusted-operator-kms-attestation",
    ),
    "restore": (
        "isolated-restore-rehearsal",
        "scripts.verify_isolated_restore",
        "machine-verified-kms-attestation",
    ),
    "deletion": (
        "deletion-boundary-rehearsal",
        "scripts.seal_deletion_boundary_observations",
        "trusted-operator-kms-attestation",
    ),
    "secret_rotation": (
        "runtime-secret-rotation",
        "scripts.seal_runtime_secret_rotation_observations",
        "trusted-operator-kms-attestation",
    ),
    "prior_worker_revocation": (
        "prior-worker-session-revocation",
        "scripts.seal_prior_worker_revocation_observations",
        "trusted-operator-kms-attestation",
    ),
}
_EXTERNAL_EVIDENCE_SUMMARY_KEYS = frozenset(
    {
        "record_id",
        "evidence_type",
        "status",
        "release_revision",
        "deployment_id",
        "completed_at",
        "content_digest",
        "issuer_role_arn",
        "signing_key_arn",
        "producer",
        "attestation_mode",
        "signed_record",
    }
)

_SIGNED_EVIDENCE_KEYS = frozenset(
    {
        "schema_version",
        "record_id",
        "evidence_type",
        "release_revision",
        "deployment_id",
        "completed_at",
        "attestation_mode",
        "attestation_outcome",
        "issuer",
        "results",
        "content_digest",
        "signature",
    }
)
_SIGNED_EVIDENCE_ISSUER_KEYS = frozenset(
    {"role_arn", "signing_key_arn", "signing_algorithm", "producer"}
)
_EVIDENCE_RESULT_KEYS = {
    "auth0-live-validation": frozenset(
        {
            "issuer_url",
            "callback_url",
            "authorization_request_id",
            "authorization_code_challenge_method",
            "authorization_response_type",
            "allowlisted_callback_request_id",
            "allowlisted_callback_status_code",
            "unallowlisted_callback_request_id",
            "unallowlisted_callback_status_code",
            "logout_request_id",
            "logout_status_code",
            "revoked_session_request_id",
            "revoked_session_status_code",
        }
    ),
    "isolated-restore-rehearsal": frozenset(
        {
            "source_identifier",
            "target_identifier",
            "database_role",
            "audit_event_id",
            "audit_fingerprint",
            "digest_subject_type",
            "digest_subject_id",
            "stored_digest",
            "row_fingerprint",
            "source_target_isolated",
            "durable_record_matched",
            "digest_matched",
        }
    ),
    "deletion-boundary-rehearsal": frozenset(
        {
            "engagement_id",
            "deletion_receipt_id",
            "application_rows_remaining",
            "current_objects_remaining",
            "object_versions_deleted",
            "delete_markers_deleted",
            "object_versions_remaining",
            "delete_markers_remaining",
            "control_engagement_id",
            "control_fingerprint_before",
            "control_fingerprint_after",
            "deletion_completed_at",
            "rds_backup_retention_days",
            "s3_noncurrent_retention_days",
            "backup_expiry_at",
        }
    ),
    "runtime-secret-rotation": frozenset(
        {
            "api_secret_arn",
            "migration_secret_arn",
            "api_previous_version_id",
            "api_current_version_id",
            "migration_previous_version_id",
            "migration_current_version_id",
            "old_api_login_sqlstate",
            "worker_group_role",
            "worker_group_login_state",
            "retired_worker_database_user",
            "current_worker_database_user",
            "prior_worker_sessions_remaining",
            "rotation_completed_at",
        }
    ),
    "prior-worker-session-revocation": frozenset({"roles"}),
}


class DeploymentQualificationError(ValueError):
    """The deployment qualification record is absent, altered, stale, or mismatched."""


@dataclass(frozen=True)
class VerifiedDeploymentQualification:
    validation_id: str
    content_digest: str
    version_id: str
    validated_at: datetime
    expires_at: datetime
    record: dict[str, Any]

    def require_current(self, *, now: datetime | None = None) -> None:
        reference = (now or datetime.now(UTC)).astimezone(UTC)
        if reference >= self.expires_at:
            raise DeploymentQualificationError("The deployment qualification record has expired.")


def readiness_validation_digest(record: dict[str, Any]) -> str:
    """Hash the pre-activation record without either digest field."""

    projection = dict(record)
    projection.pop("validation_id", None)
    projection.pop("content_digest", None)
    return canonical_sha256(projection)


def qualification_content_digest(record: dict[str, Any]) -> str:
    projection = dict(record)
    projection.pop("content_digest", None)
    return canonical_sha256(projection)


def validate_deployment_qualification_record(
    raw_record: str,
    *,
    expected_version_id: str,
    expected_release_revision: str,
    expected_deployment_id: str,
    expected_qualification_mode: str,
    expected_worker_operator_id: UUID,
    expected_worker_engagement_id: UUID,
    expected_application_origin: str,
    expected_oidc_issuer_url: str,
    expected_oidc_client_id: str,
    expected_oidc_allowed_emails: Sequence[str],
    expected_region: str,
    expected_qualifier_role_arn: str,
    expected_bedrock_model_id: str,
    expected_bedrock_classifications: Sequence[str],
    expected_s3_kms_key_arn: str,
    expected_qualification_secret_policy_sha256: str,
    expected_evidence_signing_public_key_der_b64: str,
    expected_evidence_signing_public_key_b64_sha256: str,
    now: datetime | None = None,
) -> VerifiedDeploymentQualification:
    """Validate one immutable Secrets Manager version against the running deployment."""

    encoded = raw_record.encode("utf-8")
    if not encoded or len(encoded) > MAX_QUALIFICATION_RECORD_BYTES:
        raise DeploymentQualificationError(
            "The deployment qualification record is empty or exceeds the bounded size."
        )
    try:
        value = json.loads(
            raw_record,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, DeploymentQualificationError) as exc:
        raise DeploymentQualificationError(
            "The deployment qualification record is not unambiguous JSON."
        ) from exc
    if not isinstance(value, dict) or set(value) != _TOP_LEVEL_KEYS:
        raise DeploymentQualificationError(
            "The deployment qualification record does not match the strict schema."
        )
    if value.get("schema_version") != QUALIFICATION_SCHEMA_VERSION:
        raise DeploymentQualificationError("The deployment qualification schema is unsupported.")
    if value.get("status") != "passed":
        raise DeploymentQualificationError("The deployment qualification did not pass.")

    account_id = value.get("aws_account_id")
    principal_arn = value.get("aws_principal_arn")
    if not isinstance(account_id, str) or _ACCOUNT_ID.fullmatch(account_id) is None:
        raise DeploymentQualificationError("The qualification AWS account is invalid.")
    principal_match = _ROLE_ARN.fullmatch(principal_arn) if isinstance(principal_arn, str) else None
    if principal_match is None:
        raise DeploymentQualificationError("The qualification principal is not an assumed role.")
    assert isinstance(principal_arn, str)
    if not _principal_assumed_expected_role(principal_arn, expected_qualifier_role_arn):
        raise DeploymentQualificationError(
            "The qualification principal is not the dedicated qualifier role."
        )
    if principal_match.group(2) != account_id:
        raise DeploymentQualificationError(
            "The qualification account does not match the qualifier principal."
        )
    if value.get("region") != expected_region:
        raise DeploymentQualificationError("The qualification region does not match the runtime.")
    if not isinstance(value.get("region"), str) or _REGION.fullmatch(value["region"]) is None:
        raise DeploymentQualificationError("The qualification region is invalid.")
    validated_at = _parse_timestamp(value.get("validated_at"), "validated_at")
    expires_at = _parse_timestamp(value.get("expires_at"), "expires_at")
    reference = (now or datetime.now(UTC)).astimezone(UTC)
    if validated_at > reference + timedelta(minutes=5):
        raise DeploymentQualificationError("The qualification validation time is in the future.")
    if expires_at <= validated_at:
        raise DeploymentQualificationError("The qualification expiry is not after validation.")
    if expires_at > validated_at + timedelta(days=30):
        raise DeploymentQualificationError("The qualification validity exceeds 30 days.")

    release = value.get("release")
    if not isinstance(release, dict) or set(release) != _RELEASE_KEYS:
        raise DeploymentQualificationError("The qualification release claims are incomplete.")
    _require_equal(release, "git_commit", expected_release_revision)
    _require_equal(release, "deployment_id", expected_deployment_id)
    _require_equal(release, "qualification_mode", expected_qualification_mode)
    _require_equal(release, "worker_operator_id", str(expected_worker_operator_id))
    _require_equal(release, "worker_engagement_id", str(expected_worker_engagement_id))
    _require_equal(release, "application_origin", expected_application_origin)
    _require_equal(release, "oidc_issuer_url", expected_oidc_issuer_url)
    _require_equal(release, "oidc_client_id", expected_oidc_client_id)
    expected_worker_database_user = worker_database_user_for_release(
        expected_deployment_id, expected_release_revision
    )
    _require_equal(release, "worker_database_user", expected_worker_database_user)
    if (
        not isinstance(release.get("git_commit"), str)
        or _RELEASE_REVISION.fullmatch(release["git_commit"]) is None
        or release["git_commit"] == "0" * 40
    ):
        raise DeploymentQualificationError("The qualification release revision is invalid.")
    if (
        not isinstance(release.get("deployment_id"), str)
        or _DEPLOYMENT_ID.fullmatch(release["deployment_id"]) is None
    ):
        raise DeploymentQualificationError("The qualification deployment ID is invalid.")
    if release.get("qualification_mode") != "controlled-design-partner":
        raise DeploymentQualificationError("The qualification mode is unsupported.")
    if (
        not isinstance(release.get("worker_database_user"), str)
        or WORKER_DATABASE_USER_PATTERN.fullmatch(release["worker_database_user"]) is None
    ):
        raise DeploymentQualificationError(
            "The qualification worker database user is invalid."
        )
    for identity_field in ("worker_operator_id", "worker_engagement_id"):
        try:
            identity = UUID(str(release.get(identity_field)))
        except ValueError as exc:
            raise DeploymentQualificationError(
                f"The qualification {identity_field} is invalid."
            ) from exc
        if identity.int == 0 or str(identity) != release.get(identity_field):
            raise DeploymentQualificationError(
                f"The qualification {identity_field} is not a canonical nonzero UUID."
            )
    _validate_release_auth_claims(
        release,
        expected_allowed_emails=expected_oidc_allowed_emails,
    )
    model_id = release.get("bedrock_model_id")
    model_arn = release.get("bedrock_model_arn")
    model_match = _BEDROCK_ARN.fullmatch(model_arn) if isinstance(model_arn, str) else None
    if (
        not isinstance(model_id, str)
        or not model_id
        or not isinstance(model_arn, str)
        or model_match is None
        or model_match.group(2) != expected_region
        or "*" in model_arn
        or model_id != model_match.group(3)
    ):
        raise DeploymentQualificationError("The qualification Bedrock model binding is invalid.")
    if model_id != expected_bedrock_model_id:
        raise DeploymentQualificationError(
            "The qualification Bedrock model does not match the runtime."
        )
    classifications = release.get("bedrock_allowed_data_classifications")
    if (
        not isinstance(classifications, list)
        or not classifications
        or any(not isinstance(item, str) for item in classifications)
        or classifications != sorted(set(classifications))
        or not set(classifications) <= {"PUBLIC", "INTERNAL", "CONFIDENTIAL"}
    ):
        raise DeploymentQualificationError(
            "The qualification Bedrock data classifications are invalid."
        )
    if classifications != sorted(expected_bedrock_classifications):
        raise DeploymentQualificationError(
            "The qualification Bedrock data classifications do not match the runtime."
        )
    images = release.get("images")
    if (
        not isinstance(images, dict)
        or set(images) != {"web", "api", "worker", "migration"}
        or any(
            not isinstance(image, str) or _IMAGE.fullmatch(image) is None
            for image in images.values()
        )
    ):
        raise DeploymentQualificationError("The qualification images are not exact digests.")
    evidence_issuer_role_arn = release.get("evidence_issuer_role_arn")
    evidence_signing_key_arn = release.get("evidence_signing_key_arn")
    evidence_public_key = release.get("evidence_signing_public_key_der_b64")
    evidence_public_key_fingerprint = release.get(
        "evidence_signing_public_key_b64_sha256"
    )
    issuer_match = (
        _IAM_ROLE_ARN.fullmatch(evidence_issuer_role_arn)
        if isinstance(evidence_issuer_role_arn, str)
        else None
    )
    signing_key_match = (
        _KMS_KEY_ARN.fullmatch(evidence_signing_key_arn)
        if isinstance(evidence_signing_key_arn, str)
        else None
    )
    if issuer_match is None or issuer_match.group(2) != account_id:
        raise DeploymentQualificationError(
            "The qualification evidence issuer role is invalid."
        )
    if (
        signing_key_match is None
        or signing_key_match.group(2) != expected_region
        or signing_key_match.group(3) != account_id
    ):
        raise DeploymentQualificationError(
            "The qualification evidence signing key is invalid."
        )
    if (
        evidence_public_key != expected_evidence_signing_public_key_der_b64
        or evidence_public_key_fingerprint
        != expected_evidence_signing_public_key_b64_sha256
    ):
        raise DeploymentQualificationError(
            "The qualification evidence public key does not match the runtime trust anchor."
        )
    verification_key = _load_evidence_public_key(
        evidence_public_key,
        evidence_public_key_fingerprint,
    )
    checks = value.get("checks")
    if not isinstance(checks, dict) or set(checks) != _CHECK_KEYS:
        raise DeploymentQualificationError("The qualification checks are incomplete.")
    for check_name, check in checks.items():
        if check_name == "runtime_secrets":
            if (
                not isinstance(check, dict)
                or set(check) != {"api", "migration"}
                or any(
                    not isinstance(runtime_check, dict)
                    or runtime_check.get("status") != "passed"
                    for runtime_check in check.values()
                )
            ):
                raise DeploymentQualificationError(
                    "The qualification runtime-secret checks did not pass."
                )
        elif check_name in {"prior_worker_identity_denials", "standalone_task_drain"}:
            continue
        elif not isinstance(check, dict) or check.get("status") != "passed":
            raise DeploymentQualificationError(
                f"The qualification check {check_name} did not pass."
            )
    _validate_ecs_role_bindings(
        release,
        checks,
        expected_account_id=account_id,
    )
    task_role_claims = cast(dict[str, Any], release["task_role_arns"])
    _validate_worker_database_identity(
        checks.get("worker_database_identity"),
        expected_worker_database_user=expected_worker_database_user,
        expected_worker_role_arn=str(task_role_claims["worker"]),
        expected_account_id=account_id,
        expected_region=expected_region,
    )
    _validate_worker_s3_isolation(
        checks.get("worker_s3_isolation"),
        expected_worker_engagement_id=str(expected_worker_engagement_id),
    )
    _validate_worker_bedrock_isolation(
        checks.get("worker_bedrock_isolation"),
        expected_model_arn=str(model_arn),
    )
    worker_identity_check = checks["worker_database_identity"]
    assert isinstance(worker_identity_check, dict)
    _validate_prior_worker_identity_denials(
        checks.get("prior_worker_identity_denials"),
        current_worker_role_arn=str(worker_identity_check["worker_role_arn"]),
        expected_account_id=account_id,
    )
    _validate_standalone_task_drain(
        checks.get("standalone_task_drain"),
        expected_account_id=account_id,
        expected_region=expected_region,
    )
    _validate_worker_network(checks.get("worker_network"), expected_region=expected_region)
    _validate_s3_boundary(
        checks.get("s3"),
        expected_kms_key_arn=expected_s3_kms_key_arn,
        expected_account_id=account_id,
        expected_region=expected_region,
    )
    _validate_rds_boundary(
        checks.get("rds"),
        expected_account_id=account_id,
        expected_region=expected_region,
        validated_at=validated_at,
    )
    _validate_qualification_secret_boundary(
        checks.get("qualification_secret_boundary"),
        expected_qualifier_role_arn=expected_qualifier_role_arn,
        expected_policy_sha256=expected_qualification_secret_policy_sha256,
        expected_account_id=account_id,
        expected_region=expected_region,
    )
    _validate_qualification_control_plane(
        checks.get("qualification_control_plane"),
        expected_qualifier_role_arn=expected_qualifier_role_arn,
        expected_evidence_issuer_role_arn=str(evidence_issuer_role_arn),
        expected_signing_key_arn=str(evidence_signing_key_arn),
        expected_account_id=account_id,
        expected_region=expected_region,
        expected_qualification_secret_arn=str(
            cast(dict[str, Any], checks["qualification_secret_boundary"])[
                "secret_arn"
            ]
        ),
    )
    external_evidence = value.get("external_evidence")
    if (
        not isinstance(external_evidence, dict)
        or set(external_evidence) != _EXTERNAL_EVIDENCE_KEYS
    ):
        raise DeploymentQualificationError("The qualification external evidence is incomplete.")
    for evidence_name, evidence in external_evidence.items():
        (
            expected_evidence_type,
            expected_producer,
            expected_attestation_mode,
        ) = _EXTERNAL_EVIDENCE_CONTRACT[evidence_name]
        if (
            not isinstance(evidence, dict)
            or set(evidence) != _EXTERNAL_EVIDENCE_SUMMARY_KEYS
            or not isinstance(evidence.get("record_id"), str)
            or _DEPLOYMENT_ID.fullmatch(evidence["record_id"]) is None
            or evidence.get("evidence_type") != expected_evidence_type
            or evidence.get("status") != "passed"
            or evidence.get("release_revision") != expected_release_revision
            or evidence.get("deployment_id") != expected_deployment_id
            or not isinstance(evidence.get("content_digest"), str)
            or _DIGEST.fullmatch(evidence["content_digest"]) is None
            or evidence.get("issuer_role_arn") != evidence_issuer_role_arn
            or evidence.get("signing_key_arn") != evidence_signing_key_arn
            or evidence.get("producer") != expected_producer
            or evidence.get("attestation_mode") != expected_attestation_mode
        ):
            raise DeploymentQualificationError(
                "The qualification contains invalid external evidence."
            )
        completed_at = _parse_timestamp(evidence.get("completed_at"), "completed_at")
        if (
            completed_at > validated_at + timedelta(minutes=5)
            or completed_at < validated_at - timedelta(days=30)
        ):
            raise DeploymentQualificationError(
                "The qualification contains stale or future external evidence."
            )
        _verify_signed_external_evidence(
            evidence,
            verification_key=verification_key,
            expected_evidence_type=expected_evidence_type,
            expected_producer=expected_producer,
            expected_attestation_mode=expected_attestation_mode,
            expected_release_revision=expected_release_revision,
            expected_deployment_id=expected_deployment_id,
            expected_issuer_role_arn=str(evidence_issuer_role_arn),
            expected_signing_key_arn=str(evidence_signing_key_arn),
        )
        if evidence_name == "auth0":
            signed_record = evidence["signed_record"]
            assert isinstance(signed_record, dict)
            auth_results = signed_record["results"]
            assert isinstance(auth_results, dict)
            if (
                auth_results.get("issuer_url") != release["oidc_issuer_url"]
                or auth_results.get("callback_url")
                != f"{release['application_origin']}/api/auth/callback"
            ):
                raise DeploymentQualificationError(
                    "The signed Auth0 observations do not match the release auth binding."
                )
    prior_denials = checks["prior_worker_identity_denials"]
    prior_revocation = external_evidence["prior_worker_revocation"]
    secret_rotation = external_evidence["secret_rotation"]
    assert isinstance(prior_denials, dict) and isinstance(prior_revocation, dict)
    assert isinstance(secret_rotation, dict)
    _validate_runtime_secret_bindings(
        checks.get("runtime_secrets"),
        secret_rotation,
        expected_account_id=account_id,
        expected_region=expected_region,
        validated_at=validated_at,
    )
    if (
        prior_denials.get("revocation_evidence_content_digest")
        != prior_revocation.get("content_digest")
    ):
        raise DeploymentQualificationError(
            "Prior-worker denial claims are not bound to the signed revocation evidence."
        )
    _validate_prior_worker_evidence_link(prior_denials, prior_revocation)

    supplied_validation_id = value.get("validation_id")
    supplied_content_digest = value.get("content_digest")
    if (
        not isinstance(supplied_validation_id, str)
        or _DIGEST.fullmatch(supplied_validation_id) is None
    ):
        raise DeploymentQualificationError("The qualification validation ID is invalid.")
    if (
        not isinstance(supplied_content_digest, str)
        or _DIGEST.fullmatch(supplied_content_digest) is None
    ):
        raise DeploymentQualificationError("The qualification content digest is invalid.")
    calculated_validation_id = readiness_validation_digest(value)
    calculated_content_digest = qualification_content_digest(value)
    if not hmac.compare_digest(supplied_validation_id, calculated_validation_id):
        raise DeploymentQualificationError("The qualification validation ID does not match.")
    if not hmac.compare_digest(supplied_content_digest, calculated_content_digest):
        raise DeploymentQualificationError("The qualification content digest does not match.")
    if _VERSION_ID.fullmatch(expected_version_id) is None:
        raise DeploymentQualificationError("The qualification secret version ID is invalid.")
    if not hmac.compare_digest(expected_version_id, supplied_validation_id.removeprefix("sha256:")):
        raise DeploymentQualificationError(
            "The qualification secret version does not match the validation record."
        )

    result = VerifiedDeploymentQualification(
        validation_id=supplied_validation_id,
        content_digest=supplied_content_digest,
        version_id=expected_version_id,
        validated_at=validated_at,
        expires_at=expires_at,
        record=value,
    )
    result.require_current(now=reference)
    return result


def _validate_release_auth_claims(
    release: dict[str, Any],
    *,
    expected_allowed_emails: Sequence[str],
) -> None:
    origin = release.get("application_origin")
    issuer_url = release.get("oidc_issuer_url")
    client_id = release.get("oidc_client_id")
    emails = release.get("oidc_allowed_emails")
    if not isinstance(origin, str):
        raise DeploymentQualificationError("The qualification application origin is invalid.")
    parsed_origin = urlsplit(origin)
    if (
        parsed_origin.scheme != "https"
        or parsed_origin.hostname is None
        or parsed_origin.netloc != parsed_origin.hostname
        or parsed_origin.path
        or parsed_origin.query
        or parsed_origin.fragment
        or parsed_origin.username is not None
        or parsed_origin.password is not None
        or origin != f"https://{parsed_origin.hostname}"
    ):
        raise DeploymentQualificationError(
            "The qualification application origin is not canonical HTTPS."
        )
    if not isinstance(issuer_url, str):
        raise DeploymentQualificationError("The qualification OIDC issuer is invalid.")
    parsed_issuer = urlsplit(issuer_url)
    if (
        parsed_issuer.scheme != "https"
        or parsed_issuer.hostname is None
        or parsed_issuer.netloc != parsed_issuer.hostname
        or not parsed_issuer.path.startswith("/")
        or not parsed_issuer.path.endswith("/")
        or parsed_issuer.query
        or parsed_issuer.fragment
        or parsed_issuer.username is not None
        or parsed_issuer.password is not None
        or issuer_url
        != f"https://{parsed_issuer.hostname}{parsed_issuer.path}"
    ):
        raise DeploymentQualificationError(
            "The qualification OIDC issuer is not canonical HTTPS."
        )
    if not isinstance(client_id, str) or _OIDC_CLIENT_ID.fullmatch(client_id) is None:
        raise DeploymentQualificationError("The qualification OIDC client ID is invalid.")
    if (
        not isinstance(emails, list)
        or not emails
        or len(emails) > 100
        or any(
            not isinstance(email, str)
            or _EMAIL.fullmatch(email) is None
            or email != email.casefold()
            for email in emails
        )
        or emails != sorted(set(emails))
    ):
        raise DeploymentQualificationError(
            "The qualification OIDC allowed-email binding is invalid."
        )
    if list(expected_allowed_emails) != emails:
        raise DeploymentQualificationError(
            "The qualification OIDC allowed emails do not match the runtime."
        )


def _load_evidence_public_key(
    public_key_der_b64: object,
    expected_fingerprint: object,
) -> rsa.RSAPublicKey:
    if (
        not isinstance(public_key_der_b64, str)
        or not 512 <= len(public_key_der_b64) <= 4096
        or not isinstance(expected_fingerprint, str)
        or _DIGEST.fullmatch(expected_fingerprint) is None
    ):
        raise DeploymentQualificationError(
            "The qualification evidence public key claims are invalid."
        )
    calculated_fingerprint = (
        "sha256:" + hashlib.sha256(public_key_der_b64.encode("ascii")).hexdigest()
    )
    if not hmac.compare_digest(expected_fingerprint, calculated_fingerprint):
        raise DeploymentQualificationError(
            "The qualification evidence public key fingerprint does not match."
        )
    try:
        der = base64.b64decode(public_key_der_b64, validate=True)
        public_key = serialization.load_der_public_key(der)
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise DeploymentQualificationError(
            "The qualification evidence public key is not canonical DER base64."
        ) from exc
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size != 3072:
        raise DeploymentQualificationError(
            "The qualification evidence key must be an RSA_3072 public key."
        )
    return public_key


def _verify_signed_external_evidence(
    summary: dict[str, Any],
    *,
    verification_key: rsa.RSAPublicKey,
    expected_evidence_type: str,
    expected_producer: str,
    expected_attestation_mode: str,
    expected_release_revision: str,
    expected_deployment_id: str,
    expected_issuer_role_arn: str,
    expected_signing_key_arn: str,
) -> None:
    envelope = summary.get("signed_record")
    if not isinstance(envelope, dict) or set(envelope) != _SIGNED_EVIDENCE_KEYS:
        raise DeploymentQualificationError(
            "The qualification does not retain the complete signed evidence envelope."
        )
    issuer = envelope.get("issuer")
    results = envelope.get("results")
    expected_outcome = (
        "checks-passed"
        if expected_evidence_type == "isolated-restore-rehearsal"
        else "observations-attested"
    )
    if (
        envelope.get("schema_version") != "fdlc.production-qualification-evidence/v2"
        or envelope.get("record_id") != summary.get("record_id")
        or envelope.get("evidence_type") != expected_evidence_type
        or envelope.get("release_revision") != expected_release_revision
        or envelope.get("deployment_id") != expected_deployment_id
        or envelope.get("completed_at") != summary.get("completed_at")
        or envelope.get("attestation_mode") != expected_attestation_mode
        or envelope.get("attestation_outcome") != expected_outcome
        or envelope.get("content_digest") != summary.get("content_digest")
        or not isinstance(issuer, dict)
        or set(issuer) != _SIGNED_EVIDENCE_ISSUER_KEYS
        or issuer.get("role_arn") != expected_issuer_role_arn
        or issuer.get("signing_key_arn") != expected_signing_key_arn
        or issuer.get("signing_algorithm") != "RSASSA_PSS_SHA_256"
        or issuer.get("producer") != expected_producer
        or not isinstance(results, dict)
        or set(results) != _EVIDENCE_RESULT_KEYS[expected_evidence_type]
    ):
        raise DeploymentQualificationError(
            "The retained signed evidence envelope does not match its strict release contract."
        )
    try:
        validate_evidence_results(expected_evidence_type, results)
    except EvidenceSemanticsError as exc:
        raise DeploymentQualificationError(
            "The retained signed evidence does not prove its required outcome."
        ) from exc
    if expected_evidence_type == "prior-worker-session-revocation":
        _validate_signed_prior_worker_revocation_results(
            results,
            current_release_revision=expected_release_revision,
            current_deployment_id=expected_deployment_id,
            evidence_completed_at=_parse_timestamp(
                envelope.get("completed_at"),
                "external evidence completed_at",
            ),
        )
    digest = envelope.get("content_digest")
    signature_text = envelope.get("signature")
    if (
        not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or not isinstance(signature_text, str)
        or not 32 <= len(signature_text) <= 4096
    ):
        raise DeploymentQualificationError(
            "The retained external evidence signature claims are invalid."
        )
    unsigned = dict(envelope)
    unsigned.pop("content_digest")
    unsigned.pop("signature")
    if not hmac.compare_digest(digest, canonical_sha256(unsigned)):
        raise DeploymentQualificationError(
            "The retained external evidence digest does not match its claims."
        )
    try:
        signature = base64.b64decode(signature_text, validate=True)
        verification_key.verify(
            signature,
            bytes.fromhex(digest.removeprefix("sha256:")),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=hashes.SHA256.digest_size,
            ),
            utils.Prehashed(hashes.SHA256()),
        )
    except (ValueError, binascii.Error, InvalidSignature) as exc:
        raise DeploymentQualificationError(
            "The retained external evidence signature is invalid."
        ) from exc


def _validate_signed_prior_worker_revocation_results(
    results: dict[str, Any],
    *,
    current_release_revision: str,
    current_deployment_id: str,
    evidence_completed_at: datetime,
) -> None:
    roles = results.get("roles")
    if not isinstance(roles, list) or len(roles) > 20:
        raise DeploymentQualificationError(
            "Signed prior-worker revocation evidence has an invalid role list."
        )
    role_keys = {
        "role_arn",
        "prior_release_revision",
        "prior_deployment_id",
        "identity_state",
        "quarantine_control",
        "quarantine_policy_digest",
        "assume_role_disabled",
        "permission_grants_stripped",
        "quarantine_applied_at",
        "revocation_cutoff_at",
        "session_expiry_not_before",
        "max_session_duration_seconds",
        "propagation_wait_seconds",
        "captured_session_issued_at",
        "captured_session_expires_at",
        "live_probe_completed_at",
        "deleted_at",
        "targets",
        "probe_results",
    }
    target_keys = {
        "db_user_arn",
        "s3_object_prefix_arn",
        "kms_key_arn",
        "bedrock_model_arn",
    }
    probe_keys = {
        "rds_db_connect",
        "s3_get_current_prefix",
        "s3_put_current_prefix",
        "kms_decrypt_current_key",
        "kms_generate_data_key_current_key",
        "bedrock_invoke_current_model",
    }
    role_arns: list[str] = []
    for role in roles:
        if not isinstance(role, dict) or set(role) != role_keys:
            raise DeploymentQualificationError(
                "Signed prior-worker revocation role has the wrong schema."
            )
        role_arn = role.get("role_arn")
        role_match = _IAM_ROLE_ARN.fullmatch(role_arn) if isinstance(role_arn, str) else None
        max_session = role.get("max_session_duration_seconds")
        propagation = role.get("propagation_wait_seconds")
        targets = role.get("targets")
        probes = role.get("probe_results")
        if (
            role_match is None
            or not isinstance(role.get("prior_release_revision"), str)
            or _RELEASE_REVISION.fullmatch(role["prior_release_revision"]) is None
            or role["prior_release_revision"] == "0" * 40
            or not isinstance(role.get("prior_deployment_id"), str)
            or _DEPLOYMENT_ID.fullmatch(role["prior_deployment_id"]) is None
            or role.get("identity_state")
            not in {"retained-quarantined", "deleted-after-ttl"}
            or role.get("quarantine_control") != "inline-deny-pre-cutoff-sessions"
            or role.get("assume_role_disabled") is not True
            or role.get("permission_grants_stripped") is not True
            or not isinstance(role.get("quarantine_policy_digest"), str)
            or _DIGEST.fullmatch(role["quarantine_policy_digest"]) is None
            or type(max_session) is not int
            or not 900 <= max_session <= 43200
            or type(propagation) is not int
            or not 60 <= propagation <= 3600
            or not isinstance(targets, dict)
            or set(targets) != target_keys
            or not isinstance(probes, dict)
            or set(probes) != probe_keys
            or any(decision != "denied" for decision in probes.values())
        ):
            raise DeploymentQualificationError(
                "Signed prior-worker revocation role claims are invalid."
            )
        if (
            role["prior_release_revision"] == current_release_revision
            and role["prior_deployment_id"] == current_deployment_id
        ):
            raise DeploymentQualificationError(
                "Signed prior-worker identity equals the current release identity."
            )
        assert isinstance(role_arn, str)
        role_arns.append(role_arn)
        applied = _parse_timestamp(role.get("quarantine_applied_at"), "quarantine_applied_at")
        cutoff = _parse_timestamp(role.get("revocation_cutoff_at"), "revocation_cutoff_at")
        issued = _parse_timestamp(
            role.get("captured_session_issued_at"), "captured_session_issued_at"
        )
        captured_expiry = _parse_timestamp(
            role.get("captured_session_expires_at"),
            "captured_session_expires_at",
        )
        probe = _parse_timestamp(
            role.get("live_probe_completed_at"), "live_probe_completed_at"
        )
        session_expiry = _parse_timestamp(
            role.get("session_expiry_not_before"),
            "session_expiry_not_before",
        )
        if (
            applied > cutoff
            or issued >= cutoff
            or captured_expiry <= issued
            or captured_expiry > issued + timedelta(seconds=max_session)
            or probe >= captured_expiry
            or probe < cutoff + timedelta(seconds=propagation)
        ):
            raise DeploymentQualificationError(
                "Signed prior-worker revocation timing is invalid."
            )
        if any(
            observed > evidence_completed_at
            for observed in (applied, cutoff, issued, probe)
        ):
            raise DeploymentQualificationError(
                "Signed prior-worker observations postdate their evidence attestation."
            )
        expected_session_expiry = cutoff + timedelta(
            seconds=max_session + propagation
        )
        if session_expiry != expected_session_expiry:
            raise DeploymentQualificationError(
                "Signed prior-worker session expiry is not exact."
            )
        if role["identity_state"] == "retained-quarantined":
            if role.get("deleted_at") is not None:
                raise DeploymentQualificationError(
                    "Signed retained prior-worker role has a deletion timestamp."
                )
        else:
            deleted = _parse_timestamp(role.get("deleted_at"), "deleted_at")
            if (
                deleted < session_expiry
                or deleted < probe
                or deleted > evidence_completed_at
            ):
                raise DeploymentQualificationError(
                    "Signed prior-worker deletion occurred before session expiry."
                )
    if role_arns != sorted(set(role_arns)):
        raise DeploymentQualificationError(
            "Signed prior-worker revocation roles are not sorted and unique."
        )


def _validate_prior_worker_evidence_link(
    prior_denials: dict[str, Any],
    prior_revocation: dict[str, Any],
) -> None:
    signed_record = prior_revocation.get("signed_record")
    signed_results = (
        signed_record.get("results") if isinstance(signed_record, dict) else None
    )
    signed_roles = (
        signed_results.get("roles") if isinstance(signed_results, dict) else None
    )
    denial_roles = prior_denials.get("roles")
    if not isinstance(signed_roles, list) or not isinstance(denial_roles, list):
        raise DeploymentQualificationError(
            "Prior-worker denial claims lack signed role evidence."
        )
    signed_by_arn = {
        role.get("role_arn"): role for role in signed_roles if isinstance(role, dict)
    }
    denial_by_arn = {
        role.get("role_arn"): role for role in denial_roles if isinstance(role, dict)
    }
    if (
        len(signed_by_arn) != len(signed_roles)
        or len(denial_by_arn) != len(denial_roles)
        or set(signed_by_arn) != set(denial_by_arn)
        or prior_denials.get("first_deployment") != (not signed_roles)
    ):
        raise DeploymentQualificationError(
            "Prior-worker denial roles do not match the signed revocation evidence."
        )
    lifecycle_fields = {
        "identity_state",
        "revocation_cutoff_at",
        "live_probe_completed_at",
        "deleted_at",
    }
    for role_arn, signed_role in signed_by_arn.items():
        denial_role = denial_by_arn[role_arn]
        probes = signed_role.get("probe_results")
        live_quarantine = denial_role.get("live_quarantine")
        if (
            not isinstance(probes, dict)
            or any(
                denial_role.get(field) != signed_role.get(field)
                for field in lifecycle_fields
            )
            or any(denial_role.get(key) != decision for key, decision in probes.items())
            or (
                signed_role.get("identity_state") == "retained-quarantined"
                and (
                    not isinstance(live_quarantine, dict)
                    or live_quarantine.get("quarantine_control")
                    != signed_role.get("quarantine_control")
                    or live_quarantine.get("quarantine_policy_digest")
                    != signed_role.get("quarantine_policy_digest")
                    or live_quarantine.get("max_session_duration_seconds")
                    != signed_role.get("max_session_duration_seconds")
                    or _parse_timestamp(
                        live_quarantine.get("revocation_cutoff_at"),
                        "live quarantine revocation_cutoff_at",
                    )
                    != _parse_timestamp(
                        signed_role.get("revocation_cutoff_at"),
                        "signed revocation_cutoff_at",
                    )
                )
            )
        ):
            raise DeploymentQualificationError(
                "Prior-worker denial outcomes do not match signed live probes."
            )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DeploymentQualificationError(f"Duplicate qualification key: {key}.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise DeploymentQualificationError(f"Non-finite qualification number: {value}.")


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise DeploymentQualificationError(f"Qualification {field} must be an RFC 3339 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeploymentQualificationError(
            f"Qualification {field} must be an RFC 3339 timestamp."
        ) from exc
    if parsed.tzinfo is None:
        raise DeploymentQualificationError(f"Qualification {field} must include an offset.")
    return parsed.astimezone(UTC)


def _require_equal(record: dict[str, Any], field: str, expected: str) -> None:
    if record.get(field) != expected:
        raise DeploymentQualificationError(
            f"The qualification {field} does not match the running deployment."
        )


def _principal_assumed_expected_role(principal_arn: str, role_arn: str) -> bool:
    principal_match = _ROLE_ARN.fullmatch(principal_arn)
    role_match = _IAM_ROLE_ARN.fullmatch(role_arn)
    if principal_match is None or role_match is None:
        return False
    principal_partition, principal_account, assumed_path = principal_match.groups()
    role_partition, role_account, role_path = role_match.groups()
    assumed_role_path, separator, session_name = assumed_path.rpartition("/")
    return (
        separator == "/"
        and bool(session_name)
        and principal_partition == role_partition
        and principal_account == role_account
        and assumed_role_path == role_path
    )


def _validate_worker_database_identity(
    value: object,
    *,
    expected_worker_database_user: str,
    expected_worker_role_arn: str,
    expected_account_id: str,
    expected_region: str,
) -> None:
    expected_keys = {
        "status",
        "worker_role_arn",
        "db_user_arn",
        "worker_connect",
        "non_worker_connect",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise DeploymentQualificationError(
            "The qualification worker database identity check is incomplete."
        )
    worker_role = value.get("worker_role_arn")
    db_user_arn = value.get("db_user_arn")
    role_match = _IAM_ROLE_ARN.fullmatch(worker_role) if isinstance(worker_role, str) else None
    db_user_match = (
        _RDS_DB_USER_ARN.fullmatch(db_user_arn) if isinstance(db_user_arn, str) else None
    )
    if (
        value.get("status") != "passed"
        or value.get("worker_connect") != "allowed"
        or value.get("non_worker_connect") != "denied"
        or worker_role != expected_worker_role_arn
        or role_match is None
        or role_match.group(2) != expected_account_id
        or db_user_match is None
        or db_user_match.group(2) != expected_region
        or db_user_match.group(3) != expected_account_id
        or db_user_match.group(5) != expected_worker_database_user
    ):
        raise DeploymentQualificationError(
            "The qualification worker database identity check did not pass."
        )


def _validate_ecs_role_bindings(
    release: dict[str, Any],
    checks: dict[str, Any],
    *,
    expected_account_id: str,
) -> None:
    runtime_names = {"web", "api", "worker", "migration"}
    task_roles = release.get("task_role_arns")
    execution_roles = release.get("execution_role_arns")
    if (
        not isinstance(task_roles, dict)
        or set(task_roles) != runtime_names
        or not isinstance(execution_roles, dict)
        or set(execution_roles) != runtime_names
    ):
        raise DeploymentQualificationError(
            "The qualification ECS role claims are incomplete."
        )
    all_roles: list[str] = []
    for role_arn in (*task_roles.values(), *execution_roles.values()):
        role_match = (
            _IAM_ROLE_ARN.fullmatch(role_arn) if isinstance(role_arn, str) else None
        )
        if role_match is None or role_match.group(2) != expected_account_id:
            raise DeploymentQualificationError(
                "The qualification ECS role identity is invalid."
            )
        all_roles.append(role_arn)
    if len(all_roles) != len(set(all_roles)):
        raise DeploymentQualificationError(
            "The qualification ECS task and execution roles are not separated."
        )

    ecs = checks.get("ecs")
    if (
        not isinstance(ecs, dict)
        or ecs.get("task_role_arns") != task_roles
        or ecs.get("execution_role_arns") != execution_roles
    ):
        raise DeploymentQualificationError(
            "The qualification ECS proof is not bound to the release roles."
        )

    inventory = checks.get("ecs_data_role_inventory")
    expected_role_arns = {
        "api_task": task_roles["api"],
        "api_execution": execution_roles["api"],
        "migration_task": task_roles["migration"],
        "migration_execution": execution_roles["migration"],
    }
    if (
        not isinstance(inventory, dict)
        or set(inventory)
        != {"status", "task_role_arns", "execution_role_arns", "roles"}
        or inventory.get("status") != "passed"
        or inventory.get("task_role_arns") != task_roles
        or inventory.get("execution_role_arns") != execution_roles
        or not isinstance(inventory.get("roles"), dict)
        or set(inventory["roles"]) != set(expected_role_arns)
    ):
        raise DeploymentQualificationError(
            "The qualification API/migration IAM inventory is incomplete."
        )
    roles = cast(dict[str, Any], inventory["roles"])
    partition_match = _IAM_ROLE_ARN.fullmatch(task_roles["api"])
    assert partition_match is not None
    execution_policy_arn = (
        f"arn:{partition_match.group(1)}:iam::aws:policy/service-role/"
        "AmazonECSTaskExecutionRolePolicy"
    )
    expected_inline_names = {
        "api_task": {"evidence-objects"},
        "api_execution": {"runtime-secret"},
        "migration_task": {"package-retrieval-secret-delivery"},
        "migration_execution": {"runtime-secret"},
    }
    for role_kind, expected_role_arn in expected_role_arns.items():
        role = roles.get(role_kind)
        if not isinstance(role, dict) or set(role) != {
            "role_arn",
            "trust_policy_sha256",
            "inline_policy_sha256",
            "attached_managed_policy_arns",
            "permissions_boundary_present",
            "instance_profile_arns",
        }:
            raise DeploymentQualificationError(
                f"The qualification {role_kind} IAM inventory is incomplete."
            )
        inline_policies = role.get("inline_policy_sha256")
        allowed_inline_names = expected_inline_names[role_kind]
        required_inline_names = (
            set() if role_kind == "migration_task" else allowed_inline_names
        )
        attached = (
            [execution_policy_arn] if role_kind.endswith("_execution") else []
        )
        if (
            role.get("role_arn") != expected_role_arn
            or not isinstance(role.get("trust_policy_sha256"), str)
            or _DIGEST.fullmatch(role["trust_policy_sha256"]) is None
            or not isinstance(inline_policies, dict)
            or not required_inline_names <= set(inline_policies) <= allowed_inline_names
            or any(
                not isinstance(name, str)
                or not isinstance(digest, str)
                or _DIGEST.fullmatch(digest) is None
                for name, digest in inline_policies.items()
            )
            or role.get("attached_managed_policy_arns") != attached
            or role.get("permissions_boundary_present") is not False
            or role.get("instance_profile_arns") != []
        ):
            raise DeploymentQualificationError(
                f"The qualification {role_kind} IAM inventory is invalid."
            )


def _validate_worker_s3_isolation(
    value: object,
    *,
    expected_worker_engagement_id: str,
) -> None:
    expected = {
        "status": "passed",
        "worker_engagement_id": expected_worker_engagement_id,
        "assigned_prefix_get_object": "allowed",
        "assigned_prefix_get_object_version": "allowed",
        "cross_engagement_get_object": "denied",
        "cross_engagement_get_object_version": "denied",
        "assigned_prefix_put_object": "denied",
        "assigned_prefix_delete_object": "denied",
        "assigned_prefix_delete_object_version": "denied",
        "list_bucket": "denied",
        "get_bucket_location": "denied",
        "kms_decrypt_via_s3": "allowed",
        "kms_decrypt_direct": "denied",
    }
    if not isinstance(value, dict) or value != expected:
        raise DeploymentQualificationError(
            "The qualification worker S3 isolation check did not prove the exact boundary."
        )


def _validate_worker_bedrock_isolation(
    value: object,
    *,
    expected_model_arn: str,
) -> None:
    expected = {
        "status": "passed",
        "configured_model_arn": expected_model_arn,
        "configured_model_invoke": "allowed",
        "alternate_model_invoke": "denied",
        "alternate_region_model_invoke": "denied",
    }
    if not isinstance(value, dict) or value != expected:
        raise DeploymentQualificationError(
            "The qualification worker Bedrock isolation check did not prove the exact boundary."
        )


def _validate_runtime_secret_bindings(
    value: object,
    secret_rotation: dict[str, Any],
    *,
    expected_account_id: str,
    expected_region: str,
    validated_at: datetime,
) -> None:
    signed_record = secret_rotation.get("signed_record")
    results = signed_record.get("results") if isinstance(signed_record, dict) else None
    if not isinstance(value, dict) or set(value) != {"api", "migration"}:
        raise DeploymentQualificationError(
            "The qualification runtime-secret bindings are incomplete."
        )
    if not isinstance(results, dict):
        raise DeploymentQualificationError(
            "The signed secret-rotation evidence has no typed results."
        )
    expected_keys = {
        "status",
        "secret_arn",
        "last_changed",
        "maximum_age_days",
        "current_version_id",
        "current_version_created_at",
        "awscurrent_count",
        "observed_version_count",
        "task_definition_registered_at",
        "ecs_value_from",
    }
    secret_arns: list[str] = []
    for runtime_name in ("api", "migration"):
        check = value.get(runtime_name)
        if not isinstance(check, dict) or set(check) != expected_keys:
            raise DeploymentQualificationError(
                f"The qualification {runtime_name} secret binding is incomplete."
            )
        secret_arn = check.get("secret_arn")
        secret_match = (
            _SECRET_ARN.fullmatch(secret_arn) if isinstance(secret_arn, str) else None
        )
        maximum_age_days = check.get("maximum_age_days")
        observed_version_count = check.get("observed_version_count")
        current_version_id = check.get("current_version_id")
        expected_secret_names = {
            "api": {"AI_FDE_DATABASE_URL", "AI_FDE_OIDC_CLIENT_SECRET"},
            "migration": {
                "AI_FDE_MIGRATION_DATABASE_URL",
                "AI_FDE_APP_DATABASE_PASSWORD",
            },
        }[runtime_name]
        expected_ecs_value_from = (
            {
                name: f"{secret_arn}:{name}::{current_version_id}"
                for name in expected_secret_names
            }
            if isinstance(secret_arn, str) and isinstance(current_version_id, str)
            else None
        )
        if (
            check.get("status") != "passed"
            or secret_match is None
            or secret_match.group(2) != expected_region
            or secret_match.group(3) != expected_account_id
            or type(maximum_age_days) is not int
            or not 1 <= maximum_age_days <= 90
            or check.get("awscurrent_count") != 1
            or type(observed_version_count) is not int
            or observed_version_count < 1
            or not isinstance(current_version_id, str)
            or _SECRET_VERSION_ID.fullmatch(current_version_id) is None
            or current_version_id
            != results.get(f"{runtime_name}_current_version_id")
            or check.get("ecs_value_from") != expected_ecs_value_from
        ):
            raise DeploymentQualificationError(
                f"The qualification {runtime_name} secret binding is invalid."
            )
        assert isinstance(secret_arn, str)
        last_changed = _parse_timestamp(
            check.get("last_changed"), f"{runtime_name} secret last_changed"
        )
        current_created = _parse_timestamp(
            check.get("current_version_created_at"),
            f"{runtime_name} AWSCURRENT creation",
        )
        registered_at = _parse_timestamp(
            check.get("task_definition_registered_at"),
            f"{runtime_name} task-definition registration",
        )
        if (
            current_created > registered_at
            or last_changed > validated_at + timedelta(minutes=5)
            or last_changed < validated_at - timedelta(days=maximum_age_days)
        ):
            raise DeploymentQualificationError(
                f"The qualification {runtime_name} secret is not bound to the settled task."
            )
        secret_arns.append(secret_arn)
    if len(secret_arns) != len(set(secret_arns)):
        raise DeploymentQualificationError(
            "The qualification runtime secrets are not role-separated."
        )


def _validate_s3_boundary(
    value: object,
    *,
    expected_kms_key_arn: str,
    expected_account_id: str,
    expected_region: str,
) -> None:
    expected_keys = {
        "status",
        "bucket",
        "encryption",
        "kms_key_arn",
        "bucket_policy_sha256",
        "secure_transport_required",
        "explicit_sse_kms_headers_required",
        "versioning",
        "noncurrent_retention_days",
    }
    kms_match = _KMS_KEY_ARN.fullmatch(expected_kms_key_arn)
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or value.get("status") != "passed"
        or not isinstance(value.get("bucket"), str)
        or not 3 <= len(value["bucket"]) <= 63
        or value.get("encryption") != "aws:kms"
        or value.get("kms_key_arn") != expected_kms_key_arn
        or kms_match is None
        or kms_match.group(2) != expected_region
        or kms_match.group(3) != expected_account_id
        or not isinstance(value.get("bucket_policy_sha256"), str)
        or _DIGEST.fullmatch(value["bucket_policy_sha256"]) is None
        or value.get("secure_transport_required") is not True
        or value.get("explicit_sse_kms_headers_required") is not True
        or value.get("versioning") != "Enabled"
        or type(value.get("noncurrent_retention_days")) is not int
        or not 7 <= value["noncurrent_retention_days"] <= 90
    ):
        raise DeploymentQualificationError(
            "The qualification evidence bucket boundary did not pass."
        )


def _validate_rds_boundary(
    value: object,
    *,
    expected_account_id: str,
    expected_region: str,
    validated_at: datetime,
) -> None:
    expected_keys = {
        "status",
        "identifier",
        "multi_az",
        "backup_retention_days",
        "latest_restorable_time",
        "maximum_rpo_minutes",
        "iam_database_authentication",
        "db_resource_id",
        "endpoint_address",
        "endpoint_port",
        "database_name",
        "engine",
        "vpc_id",
        "database_subnet_ids",
        "security_group_ids",
        "storage_encrypted",
        "kms_key_arn",
        "publicly_accessible",
        "deletion_protection",
        "force_ssl",
        "ca_bundle_path",
        "ca_bundle_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise DeploymentQualificationError(
            "The qualification RDS boundary is incomplete."
        )
    kms_key_arn = value.get("kms_key_arn")
    kms_match = (
        _KMS_KEY_ARN.fullmatch(kms_key_arn)
        if isinstance(kms_key_arn, str)
        else None
    )
    maximum_rpo_minutes = value.get("maximum_rpo_minutes")
    backup_retention_days = value.get("backup_retention_days")
    subnets = value.get("database_subnet_ids")
    security_groups = value.get("security_group_ids")
    if (
        value.get("status") != "passed"
        or not isinstance(value.get("identifier"), str)
        or not value["identifier"]
        or value.get("multi_az") is not True
        or type(backup_retention_days) is not int
        or not 7 <= backup_retention_days <= 35
        or type(maximum_rpo_minutes) is not int
        or not 1 <= maximum_rpo_minutes <= 60
        or value.get("iam_database_authentication") != "enabled"
        or not isinstance(value.get("db_resource_id"), str)
        or not value["db_resource_id"]
        or not isinstance(value.get("endpoint_address"), str)
        or not value["endpoint_address"].endswith(f".{expected_region}.rds.amazonaws.com")
        or value.get("endpoint_port") != 5432
        or not isinstance(value.get("database_name"), str)
        or not value["database_name"]
        or value.get("engine") != "postgres"
        or not isinstance(value.get("vpc_id"), str)
        or not value["vpc_id"].startswith("vpc-")
        or not isinstance(subnets, list)
        or len(subnets) < 2
        or any(not isinstance(item, str) or not item.startswith("subnet-") for item in subnets)
        or subnets != sorted(set(subnets))
        or not isinstance(security_groups, list)
        or len(security_groups) != 1
        or any(
            not isinstance(item, str) or not item.startswith("sg-")
            for item in security_groups
        )
        or security_groups != sorted(set(security_groups))
        or value.get("storage_encrypted") is not True
        or kms_match is None
        or kms_match.group(2) != expected_region
        or kms_match.group(3) != expected_account_id
        or value.get("publicly_accessible") is not False
        or value.get("deletion_protection") is not True
        or value.get("force_ssl") is not True
        or value.get("ca_bundle_path") != "/opt/ai-fde/certs/aws-rds-global-bundle.pem"
        or value.get("ca_bundle_sha256")
        != "sha256:e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
    ):
        raise DeploymentQualificationError(
            "The qualification RDS boundary did not prove the exact production controls."
        )
    latest_restorable_time = _parse_timestamp(
        value.get("latest_restorable_time"), "RDS latest restorable time"
    )
    assert isinstance(maximum_rpo_minutes, int)
    if not (
        validated_at - timedelta(minutes=maximum_rpo_minutes)
        <= latest_restorable_time
        <= validated_at + timedelta(minutes=5)
    ):
        raise DeploymentQualificationError(
            "The qualification RDS point-in-time restore proof is outside its RPO."
        )


def _validate_qualification_secret_boundary(
    value: object,
    *,
    expected_qualifier_role_arn: str,
    expected_policy_sha256: str,
    expected_account_id: str,
    expected_region: str,
) -> None:
    if not isinstance(value, dict) or set(value) != {
        "status",
        "secret_arn",
        "only_writer_role_arn",
        "policy_sha256",
    }:
        raise DeploymentQualificationError(
            "The qualification-secret boundary is incomplete."
        )
    secret_arn = value.get("secret_arn")
    secret_match = (
        _SECRET_ARN.fullmatch(secret_arn) if isinstance(secret_arn, str) else None
    )
    policy_sha256 = value.get("policy_sha256")
    if (
        value.get("status") != "passed"
        or secret_match is None
        or secret_match.group(2) != expected_region
        or secret_match.group(3) != expected_account_id
        or value.get("only_writer_role_arn") != expected_qualifier_role_arn
        or not isinstance(policy_sha256, str)
        or _DIGEST.fullmatch(policy_sha256) is None
        or policy_sha256 != expected_policy_sha256
    ):
        raise DeploymentQualificationError(
            "The qualification-secret boundary did not prove its exact resource policy."
        )


def _validate_qualification_control_plane(
    value: object,
    *,
    expected_qualifier_role_arn: str,
    expected_evidence_issuer_role_arn: str,
    expected_signing_key_arn: str,
    expected_account_id: str,
    expected_region: str,
    expected_qualification_secret_arn: str,
) -> None:
    if not isinstance(value, dict) or set(value) != {
        "status",
        "qualification_secret_arn",
        "signing_key_arn",
        "roles",
        "simulations",
    }:
        raise DeploymentQualificationError(
            "The qualification control-plane proof is incomplete."
        )
    roles = value.get("roles")
    simulations = value.get("simulations")
    role_keys = {
        "role_arn",
        "trusted_principal_arn",
        "trust_policy_sha256",
        "inline_policy_sha256",
        "attached_managed_policy_arns",
        "instance_profile_arns",
        "permissions_boundary_present",
    }
    if (
        value.get("status") != "passed"
        or value.get("qualification_secret_arn")
        != expected_qualification_secret_arn
        or value.get("signing_key_arn") != expected_signing_key_arn
        or not isinstance(roles, dict)
        or set(roles) != {"qualifier", "deployment", "evidence_issuer"}
        or any(not isinstance(role, dict) or set(role) != role_keys for role in roles.values())
        or not isinstance(simulations, dict)
    ):
        raise DeploymentQualificationError(
            "The qualification control-plane proof is invalid."
        )
    expected_role_arns = {
        "qualifier": expected_qualifier_role_arn,
        "evidence_issuer": expected_evidence_issuer_role_arn,
    }
    observed_role_arns: list[str] = []
    for role_kind, role_value in roles.items():
        assert isinstance(role_value, dict)
        role_arn = role_value.get("role_arn")
        role_match = _IAM_ROLE_ARN.fullmatch(role_arn) if isinstance(role_arn, str) else None
        trusted_principal_arn = role_value.get("trusted_principal_arn")
        trust_digest = role_value.get("trust_policy_sha256")
        inline_digests = role_value.get("inline_policy_sha256")
        if (
            role_match is None
            or role_match.group(2) != expected_account_id
            or role_arn != expected_role_arns.get(role_kind, role_arn)
            or not isinstance(trusted_principal_arn, str)
            or re.fullmatch(
                rf"arn:{re.escape(role_match.group(1))}:iam::{expected_account_id}:"
                r"(?:role|user)/[A-Za-z0-9+=,.@_/-]+",
                trusted_principal_arn,
            )
            is None
            or not isinstance(trust_digest, str)
            or _DIGEST.fullmatch(trust_digest) is None
            or not isinstance(inline_digests, dict)
            or len(inline_digests) != 1
            or any(
                not isinstance(name, str)
                or not name
                or not isinstance(digest, str)
                or _DIGEST.fullmatch(digest) is None
                for name, digest in inline_digests.items()
            )
            or role_value.get("attached_managed_policy_arns") != []
            or role_value.get("instance_profile_arns") != []
            or role_value.get("permissions_boundary_present") is not False
        ):
            raise DeploymentQualificationError(
                f"The qualification {role_kind} role inventory is invalid."
            )
        assert isinstance(role_arn, str)
        observed_role_arns.append(role_arn)
    if len(observed_role_arns) != len(set(observed_role_arns)):
        raise DeploymentQualificationError(
            "The qualification control roles are not separated."
        )
    expected_simulations = {
        f"{role_kind}_{action}": (
            "allowed"
            if role_kind == "qualifier" and action == "PutSecretValue"
            else "denied"
        )
        for role_kind in ("qualifier", "deployment", "evidence_issuer")
        for action in (
            "DeleteResourcePolicy",
            "DeleteSecret",
            "PutResourcePolicy",
            "PutSecretValue",
            "RotateSecret",
            "UpdateSecret",
            "UpdateSecretVersionStage",
        )
    }
    expected_simulations.update(
        {
            "qualifier_kms_sign": "denied",
            "deployment_kms_sign": "denied",
            "evidence_issuer_kms_sign": "allowed",
        }
    )
    if simulations != expected_simulations:
        raise DeploymentQualificationError(
            "The qualification two-party IAM simulation matrix is invalid."
        )
    signing_key_match = _KMS_KEY_ARN.fullmatch(expected_signing_key_arn)
    if (
        signing_key_match is None
        or signing_key_match.group(2) != expected_region
        or signing_key_match.group(3) != expected_account_id
    ):
        raise DeploymentQualificationError(
            "The qualification control-plane signing key is invalid."
        )


def _validate_prior_worker_identity_denials(
    value: object,
    *,
    current_worker_role_arn: str,
    expected_account_id: str,
) -> None:
    if not isinstance(value, dict) or set(value) != {
        "status",
        "first_deployment",
        "revocation_evidence_content_digest",
        "roles",
    }:
        raise DeploymentQualificationError(
            "The qualification prior-worker denial check is incomplete."
        )
    roles = value.get("roles")
    denial_keys = {
        "role_arn",
        "rds_db_connect",
        "s3_get_current_prefix",
        "s3_put_current_prefix",
        "kms_decrypt_current_key",
        "kms_generate_data_key_current_key",
        "bedrock_invoke_current_model",
        "identity_state",
        "iam_get_role",
        "revocation_cutoff_at",
        "live_probe_completed_at",
        "deleted_at",
        "live_quarantine",
    }
    if (
        value.get("status") != "passed"
        or type(value.get("first_deployment")) is not bool
        or not isinstance(value.get("revocation_evidence_content_digest"), str)
        or _DIGEST.fullmatch(value["revocation_evidence_content_digest"]) is None
        or not isinstance(roles, list)
        or len(roles) > 20
        or any(not isinstance(role, dict) or set(role) != denial_keys for role in roles)
    ):
        raise DeploymentQualificationError(
            "The qualification prior-worker denial check did not pass."
        )
    role_arns = [role.get("role_arn") for role in roles]
    role_matches = [
        _IAM_ROLE_ARN.fullmatch(role_arn) if isinstance(role_arn, str) else None
        for role_arn in role_arns
    ]
    if (
        any(match is None or match.group(2) != expected_account_id for match in role_matches)
        or role_arns != sorted(set(role_arns))
        or current_worker_role_arn in role_arns
        or value["first_deployment"] != (not roles)
        or any(
            role.get(key) != "denied"
            for role in roles
            for key in {
                "rds_db_connect",
                "s3_get_current_prefix",
                "s3_put_current_prefix",
                "kms_decrypt_current_key",
                "kms_generate_data_key_current_key",
                "bedrock_invoke_current_model",
            }
        )
    ):
        raise DeploymentQualificationError(
            "The qualification prior-worker denial claims are invalid."
        )
    for role in roles:
        state = role["identity_state"]
        live_quarantine = role["live_quarantine"]
        if (
            state not in {"retained-quarantined", "deleted-after-ttl"}
            or (state == "retained-quarantined" and role["iam_get_role"] != "present")
            or (state == "deleted-after-ttl" and role["iam_get_role"] != "NoSuchEntity")
            or (state == "retained-quarantined" and role["deleted_at"] is not None)
            or (state == "deleted-after-ttl" and live_quarantine is not None)
        ):
            raise DeploymentQualificationError(
                "The qualification prior-worker lifecycle state is invalid."
            )
        cutoff = _parse_timestamp(role["revocation_cutoff_at"], "revocation_cutoff_at")
        probe = _parse_timestamp(
            role["live_probe_completed_at"], "live_probe_completed_at"
        )
        if probe < cutoff:
            raise DeploymentQualificationError(
                "The qualification prior-worker probe predates revocation."
            )
        if state == "deleted-after-ttl":
            deleted = _parse_timestamp(role["deleted_at"], "deleted_at")
            if deleted < probe:
                raise DeploymentQualificationError(
                    "The qualification prior-worker deletion predates its final probe."
                )
        if state == "retained-quarantined":
            expected_live_keys = {
                "quarantine_control",
                "quarantine_policy_name",
                "quarantine_policy_digest",
                "revocation_cutoff_at",
                "max_session_duration_seconds",
                "assume_role_disabled",
                "sole_inline_policy",
                "attached_managed_policy_count",
                "permissions_boundary_present",
                "instance_profile_count",
            }
            if (
                not isinstance(live_quarantine, dict)
                or set(live_quarantine) != expected_live_keys
                or live_quarantine.get("quarantine_control")
                != "inline-deny-pre-cutoff-sessions"
                or live_quarantine.get("quarantine_policy_name")
                != "AWSRevokeOlderSessions"
                or not isinstance(live_quarantine.get("quarantine_policy_digest"), str)
                or _DIGEST.fullmatch(live_quarantine["quarantine_policy_digest"])
                is None
                or live_quarantine.get("assume_role_disabled") is not True
                or live_quarantine.get("sole_inline_policy") is not True
                or live_quarantine.get("attached_managed_policy_count") != 0
                or live_quarantine.get("permissions_boundary_present") is not False
                or live_quarantine.get("instance_profile_count") != 0
                or type(live_quarantine.get("max_session_duration_seconds")) is not int
                or not 900
                <= live_quarantine["max_session_duration_seconds"]
                <= 43200
            ):
                raise DeploymentQualificationError(
                    "The qualification retained-role quarantine proof is invalid."
                )
            if _parse_timestamp(
                live_quarantine.get("revocation_cutoff_at"),
                "live quarantine revocation_cutoff_at",
            ) != cutoff:
                raise DeploymentQualificationError(
                    "The live quarantine cutoff differs from signed evidence."
                )


def _validate_standalone_task_drain(
    value: object,
    *,
    expected_account_id: str,
    expected_region: str,
) -> None:
    expected_keys = {
        "status",
        "cluster",
        "services",
        "cluster_running_task_arns",
        "cluster_stopped_task_history",
        "enumerated_desired_statuses",
        "migration_task_definition_arn",
        "migration_tasks",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise DeploymentQualificationError(
            "The qualification standalone-task drain check is incomplete."
        )
    cluster = value.get("cluster")
    services = value.get("services")
    running = value.get("cluster_running_task_arns")
    stopped = value.get("cluster_stopped_task_history")
    migration_definition = value.get("migration_task_definition_arn")
    migration_match = (
        _TASK_DEFINITION_ARN.fullmatch(migration_definition)
        if isinstance(migration_definition, str)
        else None
    )
    if (
        value.get("status") != "passed"
        or not isinstance(cluster, str)
        or _BOUNDED_IDENTIFIER.fullmatch(cluster) is None
        or not isinstance(services, dict)
        or set(services) != {"web", "api", "worker"}
        or not isinstance(running, list)
        or running != sorted(set(running))
        or not isinstance(stopped, list)
        or value.get("enumerated_desired_statuses") != ["RUNNING", "STOPPED"]
        or value.get("migration_tasks") != []
        or migration_match is None
        or migration_match.group(2) != expected_region
        or migration_match.group(3) != expected_account_id
    ):
        raise DeploymentQualificationError(
            "The qualification standalone-task drain check did not pass."
        )
    observed_running: list[str] = []
    observed_stopped: list[str] = []
    service_by_name: dict[str, dict[str, Any]] = {}
    for runtime_name, service in services.items():
        task_definition_arn = (
            service.get("task_definition_arn") if isinstance(service, dict) else None
        )
        task_definition_match = (
            _TASK_DEFINITION_ARN.fullmatch(task_definition_arn)
            if isinstance(task_definition_arn, str)
            else None
        )
        if (
            not isinstance(service, dict)
            or set(service)
            != {
                "service",
                "task_definition_arn",
                "desired_count",
                "running_task_arns",
                "stopped_task_arns",
            }
            or not isinstance(service.get("service"), str)
            or _BOUNDED_IDENTIFIER.fullmatch(service["service"]) is None
            or type(service.get("desired_count")) is not int
            or service["desired_count"] <= 0
            or not isinstance(service.get("running_task_arns"), list)
            or len(service["running_task_arns"]) != service["desired_count"]
            or service["running_task_arns"] != sorted(set(service["running_task_arns"]))
            or not isinstance(service.get("stopped_task_arns"), list)
            or service["stopped_task_arns"]
            != sorted(set(service["stopped_task_arns"]))
            or task_definition_match is None
            or task_definition_match.group(2) != expected_region
            or task_definition_match.group(3) != expected_account_id
        ):
            raise DeploymentQualificationError(
                "The qualification standalone-task drain claims are invalid."
            )
        for task_arn in service["running_task_arns"]:
            task_match = _TASK_ARN.fullmatch(task_arn) if isinstance(task_arn, str) else None
            if (
                task_match is None
                or task_match.group(2) != expected_region
                or task_match.group(3) != expected_account_id
                or task_match.group(4) != cluster
            ):
                raise DeploymentQualificationError(
                    "The qualification cluster task ARN is invalid."
                )
            observed_running.append(task_arn)
        observed_stopped.extend(service["stopped_task_arns"])
        service_by_name[runtime_name] = service
    if sorted(observed_running) != running or len(observed_running) != len(set(observed_running)):
        raise DeploymentQualificationError(
            "The qualification cluster task inventory is not an exact service union."
        )
    stopped_arns: list[str] = []
    stopped_by_arn: dict[str, dict[str, Any]] = {}
    for task in stopped:
        task_arn = task.get("task_arn") if isinstance(task, dict) else None
        runtime_name = task.get("runtime") if isinstance(task, dict) else None
        service = service_by_name.get(runtime_name) if isinstance(runtime_name, str) else None
        task_match = _TASK_ARN.fullmatch(task_arn) if isinstance(task_arn, str) else None
        if (
            not isinstance(task, dict)
            or set(task)
            != {
                "task_arn",
                "runtime",
                "service",
                "classification",
                "group",
                "task_definition_arn",
                "stopped_at",
            }
            or task_match is None
            or task_match.group(2) != expected_region
            or task_match.group(3) != expected_account_id
            or task_match.group(4) != cluster
            or not isinstance(task.get("group"), str)
            or not isinstance(task.get("classification"), str)
        ):
            raise DeploymentQualificationError(
                "The qualification stopped-task history is invalid."
            )
        _parse_timestamp(task.get("stopped_at"), "stopped_at")
        definition = task.get("task_definition_arn")
        definition_match = (
            _TASK_DEFINITION_ARN.fullmatch(definition)
            if isinstance(definition, str)
            else None
        )
        if (
            definition_match is None
            or definition_match.group(2) != expected_region
            or definition_match.group(3) != expected_account_id
        ):
            raise DeploymentQualificationError(
                "The qualification stopped-task definition ARN is invalid."
            )
        classification = task["classification"]
        if classification in {"current-service-revision", "prior-service-revision"}:
            if (
                runtime_name not in {"web", "api", "worker"}
                or service is None
                or task.get("service") != service["service"]
                or (
                    classification == "current-service-revision"
                    and definition != service["task_definition_arn"]
                )
                or (
                    classification == "prior-service-revision"
                    and definition == service["task_definition_arn"]
                )
            ):
                raise DeploymentQualificationError(
                    "The qualification stopped service-task classification is invalid."
                )
        elif classification == "migration":
            if runtime_name != "migration" or task.get("service") is not None:
                raise DeploymentQualificationError(
                    "The qualification stopped migration-task classification is invalid."
                )
        elif classification == "other":
            if runtime_name is not None or task.get("service") is not None:
                raise DeploymentQualificationError(
                    "The qualification stopped other-task classification is invalid."
                )
        else:
            raise DeploymentQualificationError(
                "The qualification stopped-task classification is invalid."
            )
        assert isinstance(task_arn, str)
        stopped_arns.append(task_arn)
        stopped_by_arn[task_arn] = task
    if (
        stopped_arns != sorted(set(stopped_arns))
        or len(observed_stopped) != len(set(observed_stopped))
        or any(
            task_arn not in stopped_by_arn
            or stopped_by_arn[task_arn]["classification"]
            not in {"current-service-revision", "prior-service-revision"}
            for task_arn in observed_stopped
        )
    ):
        raise DeploymentQualificationError(
            "The qualification stopped-task inventory is not an exact service union."
        )


def _validate_worker_network(value: object, *, expected_region: str) -> None:
    expected_keys = {
        "status",
        "vpc_id",
        "worker_security_group_id",
        "endpoint_security_group_id",
        "endpoint_ingress_security_group_ids",
        "endpoint_ingress_rule_count",
        "worker_subnet_ids",
        "worker_route_table_id",
        "allowed_egress_rule_count",
        "public_or_nat_routes",
        "vpc_endpoints",
    }
    resource_id = re.compile(r"(?:vpc|sg|subnet|rtb|vpce)-[0-9a-f]{8,32}")
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise DeploymentQualificationError(
            "The qualification worker network check is incomplete."
        )
    subnet_ids = value.get("worker_subnet_ids")
    endpoint_security_group_id = value.get("endpoint_security_group_id")
    endpoint_ingress_ids = value.get("endpoint_ingress_security_group_ids")
    endpoints = value.get("vpc_endpoints")
    if (
        value.get("status") != "passed"
        or not isinstance(value.get("vpc_id"), str)
        or resource_id.fullmatch(value["vpc_id"]) is None
        or not isinstance(value.get("worker_security_group_id"), str)
        or resource_id.fullmatch(value["worker_security_group_id"]) is None
        or not isinstance(endpoint_security_group_id, str)
        or resource_id.fullmatch(endpoint_security_group_id) is None
        or not isinstance(endpoint_ingress_ids, list)
        or len(endpoint_ingress_ids) != 4
        or endpoint_ingress_ids != sorted(set(endpoint_ingress_ids))
        or value["worker_security_group_id"] not in endpoint_ingress_ids
        or any(
            not isinstance(group_id, str) or resource_id.fullmatch(group_id) is None
            for group_id in endpoint_ingress_ids
        )
        or value.get("endpoint_ingress_rule_count") != 4
        or not isinstance(value.get("worker_route_table_id"), str)
        or resource_id.fullmatch(value["worker_route_table_id"]) is None
        or not isinstance(subnet_ids, list)
        or len(subnet_ids) < 2
        or subnet_ids != sorted(set(subnet_ids))
        or any(
            not isinstance(subnet_id, str) or resource_id.fullmatch(subnet_id) is None
            for subnet_id in subnet_ids
        )
        or value.get("allowed_egress_rule_count") != 5
        or value.get("public_or_nat_routes") != 0
        or not isinstance(endpoints, dict)
        or set(endpoints)
        != {"s3", "secretsmanager", "bedrock-runtime", "ecr.api", "ecr.dkr", "logs"}
    ):
        raise DeploymentQualificationError(
            "The qualification worker network check did not pass."
        )
    for endpoint_name, endpoint in endpoints.items():
        expected_type = "Gateway" if endpoint_name == "s3" else "Interface"
        attachment_keys = (
            {"route_table_ids"}
            if endpoint_name == "s3"
            else {"subnet_ids", "security_group_ids"}
        )
        if (
            not isinstance(endpoint, dict)
            or set(endpoint)
            != {"id", "service_name", "type", "policy_sha256"} | attachment_keys
            or not isinstance(endpoint.get("id"), str)
            or resource_id.fullmatch(endpoint["id"]) is None
            or endpoint.get("service_name")
            != f"com.amazonaws.{expected_region}.{endpoint_name}"
            or endpoint.get("type") != expected_type
            or not isinstance(endpoint.get("policy_sha256"), str)
            or _DIGEST.fullmatch(endpoint["policy_sha256"]) is None
        ):
            raise DeploymentQualificationError(
                "The qualification worker endpoint proof is invalid."
            )
        if endpoint_name == "s3":
            route_table_ids = endpoint.get("route_table_ids")
            if (
                not isinstance(route_table_ids, list)
                or len(route_table_ids) < 2
                or route_table_ids != sorted(set(route_table_ids))
                or value["worker_route_table_id"] not in route_table_ids
                or any(
                    not isinstance(route_table_id, str)
                    or resource_id.fullmatch(route_table_id) is None
                    for route_table_id in route_table_ids
                )
            ):
                raise DeploymentQualificationError(
                    "The qualification S3 endpoint attachments are invalid."
                )
        else:
            endpoint_subnets = endpoint.get("subnet_ids")
            endpoint_group_ids = endpoint.get("security_group_ids")
            if (
                not isinstance(endpoint_subnets, list)
                or len(endpoint_subnets) < 2
                or endpoint_subnets != sorted(set(endpoint_subnets))
                or any(
                    not isinstance(subnet_id, str)
                    or resource_id.fullmatch(subnet_id) is None
                    for subnet_id in endpoint_subnets
                )
                or endpoint_group_ids != [endpoint_security_group_id]
            ):
                raise DeploymentQualificationError(
                    "The qualification interface endpoint attachments are invalid."
                )
