from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ai_fde.modules.runtime.evidence_semantics import (
    EvidenceSemanticsError,
    validate_evidence_results,
)

EVIDENCE_SCHEMA_VERSION = "fdlc.production-qualification-evidence/v2"
SYNTHETIC_EVIDENCE_SCHEMA_VERSION = "fdlc.synthetic-qualification-evidence/v1"
MAX_EVIDENCE_BYTES = 8 * 1024
PASS_STATUS = "passed"
SIGNING_ALGORITHM = "RSASSA_PSS_SHA_256"

EVIDENCE_PRODUCERS = {
    "auth0-live-validation": "scripts.seal_auth0_observations",
    "isolated-restore-rehearsal": "scripts.verify_isolated_restore",
    "deletion-boundary-rehearsal": "scripts.seal_deletion_boundary_observations",
    "runtime-secret-rotation": "scripts.seal_runtime_secret_rotation_observations",
    "prior-worker-session-revocation": (
        "scripts.seal_prior_worker_revocation_observations"
    ),
}
EVIDENCE_TYPES = frozenset(EVIDENCE_PRODUCERS)
ATTESTATION_MODES = {
    "auth0-live-validation": "trusted-operator-kms-attestation",
    "isolated-restore-rehearsal": "machine-verified-kms-attestation",
    "deletion-boundary-rehearsal": "trusted-operator-kms-attestation",
    "runtime-secret-rotation": "trusted-operator-kms-attestation",
    "prior-worker-session-revocation": "trusted-operator-kms-attestation",
}
ATTESTATION_OUTCOMES = {
    "auth0-live-validation": "observations-attested",
    "isolated-restore-rehearsal": "checks-passed",
    "deletion-boundary-rehearsal": "observations-attested",
    "runtime-secret-rotation": "observations-attested",
    "prior-worker-session-revocation": "observations-attested",
}

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_RECORD_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{7,119}")
_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
_ROLE_ARN_PATTERN = re.compile(
    r"arn:(aws|aws-us-gov|aws-cn|aws-iso|aws-iso-b):iam::([0-9]{12}):"
    r"role/([A-Za-z0-9+=,.@_/-]{1,512})"
)
_KMS_KEY_ARN_PATTERN = re.compile(
    r"arn:(aws|aws-us-gov|aws-cn|aws-iso|aws-iso-b):kms:[a-z0-9-]{1,32}:"
    r"([0-9]{12}):key/([0-9a-fA-F-]{32,64})"
)
_TOP_LEVEL_KEYS = frozenset(
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
_ISSUER_KEYS = frozenset({"role_arn", "signing_key_arn", "signing_algorithm", "producer"})
_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "authorization_header",
        "client_secret",
        "cookie",
        "customer_evidence",
        "password",
        "prompt",
        "raw_payload",
        "refresh_token",
        "secret",
        "secret_value",
        "token",
    }
)
_GENERIC_RESULT_KEYS = frozenset({"check", "checks", "passed", "result", "status"})


class EvidenceRecordError(RuntimeError):
    """Raised when external qualification evidence is not authenticated and release-bound."""


def canonical_record_digest(record: Mapping[str, Any]) -> str:
    """Hash the signed claims, excluding only the digest and detached KMS signature."""

    payload = dict(record)
    payload.pop("content_digest", None)
    payload.pop("signature", None)
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise EvidenceRecordError(
            "Evidence contains a value that canonical JSON cannot encode."
        ) from error
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def build_signed_evidence_record(
    *,
    record_id: str,
    evidence_type: str,
    release_revision: str,
    deployment_id: str,
    completed_at: datetime,
    results: Mapping[str, Any],
    issuer_role_arn: str,
    signing_key_arn: str,
    caller_principal_arn: str,
    kms_client: Any,
) -> dict[str, Any]:
    """Build and KMS-sign one procedure-specific evidence record."""

    if completed_at.tzinfo is None:
        raise EvidenceRecordError("Evidence completed_at must include an offset.")
    _validate_identity_claims(
        record_id=record_id,
        release_revision=release_revision,
        deployment_id=deployment_id,
    )
    if evidence_type not in EVIDENCE_PRODUCERS:
        raise EvidenceRecordError(f"Unsupported external evidence type: {evidence_type}.")
    _validate_role_and_key(issuer_role_arn, signing_key_arn)
    if not principal_uses_role(caller_principal_arn, issuer_role_arn):
        raise EvidenceRecordError("The evidence signer is not using the configured issuer role.")
    result_claims = dict(results)
    _reject_sensitive_keys(result_claims)
    _validate_results(evidence_type, result_claims)
    _validate_prior_release_separation(
        evidence_type,
        result_claims,
        release_revision=release_revision,
        deployment_id=deployment_id,
    )
    _validate_prior_observation_completion(
        evidence_type,
        result_claims,
        completed_at=completed_at.astimezone(UTC),
    )
    record: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "record_id": record_id,
        "evidence_type": evidence_type,
        "release_revision": release_revision,
        "deployment_id": deployment_id,
        "completed_at": completed_at.astimezone(UTC).isoformat(),
        "attestation_mode": ATTESTATION_MODES[evidence_type],
        "attestation_outcome": ATTESTATION_OUTCOMES[evidence_type],
        "issuer": {
            "role_arn": issuer_role_arn,
            "signing_key_arn": signing_key_arn,
            "signing_algorithm": SIGNING_ALGORITHM,
            "producer": EVIDENCE_PRODUCERS[evidence_type],
        },
        "results": result_claims,
    }
    digest = canonical_record_digest(record)
    try:
        response = kms_client.sign(
            KeyId=signing_key_arn,
            Message=bytes.fromhex(digest.removeprefix("sha256:")),
            MessageType="DIGEST",
            SigningAlgorithm=SIGNING_ALGORITHM,
        )
    except Exception as error:
        raise EvidenceRecordError("AWS KMS could not sign the external evidence record.") from error
    returned_key = response.get("KeyId")
    signature = response.get("Signature")
    if returned_key != signing_key_arn or not isinstance(signature, bytes) or not signature:
        raise EvidenceRecordError("AWS KMS did not return a signature from the configured key.")
    record["content_digest"] = digest
    record["signature"] = base64.b64encode(signature).decode("ascii")
    return record


def build_synthetic_evidence_record(
    *,
    environment: str,
    record_id: str,
    evidence_type: str,
    release_revision: str,
    deployment_id: str,
    completed_at: datetime,
    checks: list[dict[str, str]],
) -> dict[str, Any]:
    """Create legacy-shaped evidence for tests/development only; production rejects it."""

    if environment not in {"development", "test"}:
        raise EvidenceRecordError("Synthetic evidence is allowed only in development or test.")
    if completed_at.tzinfo is None:
        raise EvidenceRecordError("Evidence completed_at must include an offset.")
    return {
        "schema_version": SYNTHETIC_EVIDENCE_SCHEMA_VERSION,
        "record_id": record_id,
        "evidence_type": evidence_type,
        "status": PASS_STATUS,
        "release_revision": release_revision,
        "deployment_id": deployment_id,
        "completed_at": completed_at.astimezone(UTC).isoformat(),
        "checks": checks,
    }


def load_and_validate_evidence_record(
    path: Path,
    *,
    expected_type: str,
    expected_revision: str,
    expected_deployment_id: str,
    expected_issuer_role_arn: str,
    expected_signing_key_arn: str,
    kms_client: Any,
    maximum_age_days: int = 30,
    now: datetime | None = None,
) -> dict[str, object]:
    """Fail closed on schema, typed results, provenance, signature, freshness, and binding."""

    if expected_type not in EVIDENCE_TYPES:
        raise EvidenceRecordError(f"Unsupported external evidence type: {expected_type}.")
    if not 1 <= maximum_age_days <= 90:
        raise EvidenceRecordError("External evidence age window must be between 1 and 90 days.")
    _validate_role_and_key(expected_issuer_role_arn, expected_signing_key_arn)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise EvidenceRecordError(f"External evidence record is unreadable: {path}.") from error
    if not raw or len(raw) > MAX_EVIDENCE_BYTES:
        raise EvidenceRecordError(
            f"External evidence record must contain 1-{MAX_EVIDENCE_BYTES} bytes: {path}."
        )
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, EvidenceRecordError) as error:
        raise EvidenceRecordError(
            f"External evidence record is not unambiguous JSON: {path}."
        ) from error
    if not isinstance(value, dict):
        raise EvidenceRecordError(f"External evidence record must be a JSON object: {path}.")
    if set(value) != _TOP_LEVEL_KEYS:
        raise EvidenceRecordError(
            "External evidence record keys do not match the authenticated v2 schema."
        )
    _reject_sensitive_keys(value)
    _require_equal(value, "schema_version", EVIDENCE_SCHEMA_VERSION)
    _require_equal(value, "evidence_type", expected_type)
    _require_equal(value, "release_revision", expected_revision)
    _require_equal(value, "deployment_id", expected_deployment_id)
    _require_equal(value, "attestation_mode", ATTESTATION_MODES[expected_type])
    _require_equal(value, "attestation_outcome", ATTESTATION_OUTCOMES[expected_type])
    _validate_identity_claims(
        record_id=value.get("record_id"),
        release_revision=value.get("release_revision"),
        deployment_id=value.get("deployment_id"),
    )

    completed_at = _parse_completed_at(value.get("completed_at"))
    reference_time = (now or datetime.now(UTC)).astimezone(UTC)
    if completed_at > reference_time + timedelta(minutes=5):
        raise EvidenceRecordError("External evidence completed_at is in the future.")
    if completed_at < reference_time - timedelta(days=maximum_age_days):
        raise EvidenceRecordError(
            f"External evidence is older than the {maximum_age_days}-day release window."
        )

    issuer = value.get("issuer")
    if not isinstance(issuer, dict) or set(issuer) != _ISSUER_KEYS:
        raise EvidenceRecordError("External evidence issuer has the wrong schema.")
    _require_equal(issuer, "role_arn", expected_issuer_role_arn)
    _require_equal(issuer, "signing_key_arn", expected_signing_key_arn)
    _require_equal(issuer, "signing_algorithm", SIGNING_ALGORITHM)
    _require_equal(issuer, "producer", EVIDENCE_PRODUCERS[expected_type])

    results = value.get("results")
    if not isinstance(results, dict):
        raise EvidenceRecordError("External evidence results must be an object.")
    _validate_results(expected_type, results)
    _validate_prior_release_separation(
        expected_type,
        results,
        release_revision=expected_revision,
        deployment_id=expected_deployment_id,
    )
    _validate_prior_observation_completion(
        expected_type,
        results,
        completed_at=completed_at,
    )

    supplied_digest = value.get("content_digest")
    if not isinstance(supplied_digest, str) or _DIGEST_PATTERN.fullmatch(supplied_digest) is None:
        raise EvidenceRecordError("External evidence content_digest is not a sha256 digest.")
    calculated_digest = canonical_record_digest(value)
    if not hmac.compare_digest(supplied_digest, calculated_digest):
        raise EvidenceRecordError("External evidence content_digest does not match its content.")
    signature_text = value.get("signature")
    if not isinstance(signature_text, str) or not 32 <= len(signature_text) <= 4096:
        raise EvidenceRecordError("External evidence KMS signature is not bounded base64.")
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (ValueError, TypeError) as error:
        raise EvidenceRecordError("External evidence KMS signature is not valid base64.") from error
    try:
        response = kms_client.verify(
            KeyId=expected_signing_key_arn,
            Message=bytes.fromhex(supplied_digest.removeprefix("sha256:")),
            MessageType="DIGEST",
            Signature=signature,
            SigningAlgorithm=SIGNING_ALGORITHM,
        )
    except Exception as error:
        raise EvidenceRecordError(
            "AWS KMS could not verify external evidence provenance."
        ) from error
    if (
        response.get("KeyId") != expected_signing_key_arn
        or response.get("SignatureValid") is not True
    ):
        raise EvidenceRecordError("External evidence KMS signature is invalid.")

    return {
        "record_id": value["record_id"],
        "evidence_type": expected_type,
        "status": PASS_STATUS,
        "release_revision": value["release_revision"],
        "deployment_id": value["deployment_id"],
        "completed_at": completed_at.isoformat(),
        "content_digest": supplied_digest,
        "issuer_role_arn": expected_issuer_role_arn,
        "signing_key_arn": expected_signing_key_arn,
        "producer": EVIDENCE_PRODUCERS[expected_type],
        "attestation_mode": value["attestation_mode"],
        "signed_record": value,
    }


def principal_uses_role(principal_arn: str, role_arn: str) -> bool:
    role_match = _ROLE_ARN_PATTERN.fullmatch(role_arn)
    if role_match is None:
        return False
    if hmac.compare_digest(principal_arn, role_arn):
        return True
    partition, account, role_path = role_match.groups()
    prefix = f"arn:{partition}:sts::{account}:assumed-role/{role_path}/"
    return principal_arn.startswith(prefix) and len(principal_arn) > len(prefix)


def typed_observation_sealer_cli(evidence_type: str) -> None:
    """Seal exact typed observations under the independent AWS KMS attestor identity."""

    import boto3

    if evidence_type not in EVIDENCE_PRODUCERS:
        raise EvidenceRecordError(f"Unsupported external evidence type: {evidence_type}.")
    parser = argparse.ArgumentParser(
        description=f"Validate and KMS-seal {evidence_type} typed observations."
    )
    parser.add_argument("--region", required=True)
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--release-revision", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--completed-at", required=True)
    parser.add_argument("--issuer-role-arn", required=True)
    parser.add_argument("--signing-key-arn", required=True)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise EvidenceRecordError("Evidence output already exists; refusing to overwrite it.")
    try:
        stat = args.observations.lstat()
        raw_observations = args.observations.read_bytes()
    except OSError as error:
        raise EvidenceRecordError("Procedure observation file is unreadable.") from error
    if (
        args.observations.is_symlink()
        or not args.observations.is_file()
        or stat.st_size != len(raw_observations)
    ):
        raise EvidenceRecordError("Procedure observations must be one stable regular file.")
    if not raw_observations or len(raw_observations) > MAX_EVIDENCE_BYTES:
        raise EvidenceRecordError("Procedure observation file is empty or oversized.")
    try:
        observations = json.loads(
            raw_observations,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, EvidenceRecordError) as error:
        raise EvidenceRecordError("Procedure observation file is not unambiguous JSON.") from error
    if not isinstance(observations, dict):
        raise EvidenceRecordError("Procedure observations must be a JSON object.")
    _reject_generic_result_claims(observations)
    completed_at = _parse_completed_at(args.completed_at)
    results = _derive_results_from_observations(
        evidence_type,
        observations,
        deployment_id=args.deployment_id,
        release_revision=args.release_revision,
        completed_at=completed_at,
    )
    session = boto3.Session(region_name=args.region)
    principal_arn = str(session.client("sts").get_caller_identity()["Arn"])
    record = build_signed_evidence_record(
        record_id=args.record_id,
        evidence_type=evidence_type,
        release_revision=args.release_revision,
        deployment_id=args.deployment_id,
        completed_at=completed_at,
        results=results,
        issuer_role_arn=args.issuer_role_arn,
        signing_key_arn=args.signing_key_arn,
        caller_principal_arn=principal_arn,
        kms_client=session.client("kms"),
    )
    try:
        with args.output.open("x", encoding="utf-8") as output_file:
            json.dump(record, output_file, indent=2, sort_keys=True)
            output_file.write("\n")
    except FileExistsError as error:
        raise EvidenceRecordError("Evidence output already exists; refusing overwrite.") from error
    print(json.dumps(record, indent=2, sort_keys=True))


def _validate_identity_claims(
    *, record_id: object, release_revision: object, deployment_id: object
) -> None:
    if not isinstance(record_id, str) or _RECORD_ID_PATTERN.fullmatch(record_id) is None:
        raise EvidenceRecordError("External evidence record_id is not a bounded stable identifier.")
    if (
        not isinstance(release_revision, str)
        or _REVISION_PATTERN.fullmatch(release_revision) is None
        or release_revision == "0" * 40
    ):
        raise EvidenceRecordError("External evidence release_revision is not an exact Git SHA.")
    if not isinstance(deployment_id, str) or _RECORD_ID_PATTERN.fullmatch(deployment_id) is None:
        raise EvidenceRecordError("External evidence deployment_id is not a bounded identifier.")


def _validate_role_and_key(role_arn: str, key_arn: str) -> None:
    role_match = _ROLE_ARN_PATTERN.fullmatch(role_arn)
    key_match = _KMS_KEY_ARN_PATTERN.fullmatch(key_arn)
    if role_match is None or "*" in role_arn:
        raise EvidenceRecordError("Evidence issuer role must be one exact IAM role ARN.")
    if key_match is None or "*" in key_arn:
        raise EvidenceRecordError("Evidence signing key must be one exact KMS key ARN.")
    if role_match.group(1, 2) != key_match.group(1, 2):
        raise EvidenceRecordError(
            "Evidence issuer role and signing key must share a partition/account."
        )


def _validate_results(evidence_type: str, results: Mapping[str, Any]) -> None:
    try:
        validate_evidence_results(evidence_type, results)
    except EvidenceSemanticsError as error:
        raise EvidenceRecordError(str(error)) from error


def _derive_results_from_observations(
    evidence_type: str,
    observations: Mapping[str, Any],
    *,
    deployment_id: str,
    release_revision: str,
    completed_at: datetime,
) -> dict[str, Any]:
    """Turn an exact observation schema into signed claims; callers never supply pass/fail."""

    if evidence_type == "auth0-live-validation":
        results = dict(observations)
    elif evidence_type == "deletion-boundary-rehearsal":
        _exact_keys(
            observations,
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
            },
            "deletion observation",
        )
        deleted_at = _parse_completed_at(observations["deletion_completed_at"])
        if deleted_at > completed_at:
            raise EvidenceRecordError(
                "Deletion completion cannot be later than evidence attestation."
            )
        rds_days = observations["rds_backup_retention_days"]
        s3_days = observations["s3_noncurrent_retention_days"]
        if type(rds_days) is not int or not 1 <= rds_days <= 35:
            raise EvidenceRecordError("Observed RDS backup retention must be 1-35 days.")
        if type(s3_days) is not int or not 7 <= s3_days <= 90:
            raise EvidenceRecordError("Observed S3 noncurrent retention must be 7-90 days.")
        results = {
            **observations,
            "backup_expiry_at": (
                deleted_at + timedelta(days=rds_days)
            ).isoformat(),
        }
    elif evidence_type == "runtime-secret-rotation":
        _exact_keys(
            observations,
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
                "prior_worker_sessions_remaining",
            },
            "runtime secret rotation observation",
        )
        results = {
            **observations,
            "current_worker_database_user": (
                "ai_fde_worker_"
                + hashlib.sha256(
                    f"{deployment_id}:{release_revision}".encode()
                ).hexdigest()[:12]
            ),
            "rotation_completed_at": completed_at.isoformat(),
        }
    elif evidence_type == "prior-worker-session-revocation":
        _exact_keys(observations, {"roles"}, "prior worker revocation observation")
        results = dict(observations)
    else:
        raise EvidenceRecordError(
            "Isolated restore evidence must be produced by its machine verifier."
        )
    _validate_results(evidence_type, results)
    _validate_prior_release_separation(
        evidence_type,
        results,
        release_revision=release_revision,
        deployment_id=deployment_id,
    )
    _validate_prior_observation_completion(
        evidence_type,
        results,
        completed_at=completed_at.astimezone(UTC),
    )
    return results


def _validate_prior_release_separation(
    evidence_type: str,
    results: Mapping[str, Any],
    *,
    release_revision: str,
    deployment_id: str,
) -> None:
    if evidence_type != "prior-worker-session-revocation":
        return
    roles = results.get("roles")
    if not isinstance(roles, list):
        return
    if any(
        isinstance(role, dict)
        and role.get("prior_release_revision") == release_revision
        and role.get("prior_deployment_id") == deployment_id
        for role in roles
    ):
        raise EvidenceRecordError(
            "A prior worker identity cannot equal the current release identity."
        )


def _validate_prior_observation_completion(
    evidence_type: str,
    results: Mapping[str, Any],
    *,
    completed_at: datetime,
) -> None:
    if evidence_type != "prior-worker-session-revocation":
        return
    roles = results.get("roles")
    if not isinstance(roles, list):
        return
    for role in roles:
        if not isinstance(role, dict):
            continue
        observed_times = (
            "quarantine_applied_at",
            "revocation_cutoff_at",
            "captured_session_issued_at",
            "live_probe_completed_at",
        )
        if any(_parse_completed_at(role[field]) > completed_at for field in observed_times):
            raise EvidenceRecordError(
                "Prior worker observations cannot postdate their evidence attestation."
            )
        deleted_at = role.get("deleted_at")
        if deleted_at is not None and _parse_completed_at(deleted_at) > completed_at:
            raise EvidenceRecordError(
                "Prior worker deletion cannot postdate its evidence attestation."
            )


def _exact_keys(results: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(results) != expected:
        raise EvidenceRecordError(f"{label} evidence results do not match the mandatory schema.")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceRecordError(f"Duplicate JSON key: {key}.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise EvidenceRecordError(f"Non-finite JSON number is not allowed: {value}.")


def _reject_sensitive_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = key.casefold().replace("-", "_")
            if normalized in _SENSITIVE_KEYS:
                raise EvidenceRecordError(
                    f"External evidence contains forbidden sensitive field: {key}."
                )
            _reject_sensitive_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_sensitive_keys(nested)


def _reject_generic_result_claims(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = key.casefold().replace("-", "_")
            if normalized in _GENERIC_RESULT_KEYS:
                raise EvidenceRecordError(
                    f"Typed observations cannot contain generic outcome field: {key}."
                )
            _reject_generic_result_claims(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_generic_result_claims(nested)


def _require_equal(record: Mapping[str, Any], key: str, expected: str) -> None:
    if record.get(key) != expected:
        raise EvidenceRecordError(f"External evidence {key} does not match {expected!r}.")


def _parse_completed_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise EvidenceRecordError("External evidence timestamp must be RFC 3339.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceRecordError("External evidence timestamp must be RFC 3339.") from error
    if parsed.tzinfo is None:
        raise EvidenceRecordError("External evidence timestamp must include an offset.")
    return parsed.astimezone(UTC)
