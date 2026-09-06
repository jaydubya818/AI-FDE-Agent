from __future__ import annotations

import hmac
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit


class EvidenceSemanticsError(ValueError):
    """Signed evidence has the right shape but does not prove a passing outcome."""


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{7,119}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_ROLE_ARN = re.compile(
    r"arn:(aws|aws-us-gov|aws-cn|aws-iso|aws-iso-b):iam::([0-9]{12}):"
    r"role/([A-Za-z0-9+=,.@_/-]{1,512})"
)
_SECRET_ARN = re.compile(
    r"arn:(aws|aws-us-gov|aws-cn|aws-iso|aws-iso-b):secretsmanager:[a-z0-9-]+:"
    r"[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]{1,512}"
)
_WORKER_USER = re.compile(r"ai_fde_worker_[0-9a-f]{12}")
_VERSION_ID = re.compile(r"[A-Za-z0-9-]{32,64}")


def validate_evidence_results(evidence_type: str, results: Mapping[str, Any]) -> None:
    """Validate the exact result schema and its procedure-specific pass semantics."""

    validators = {
        "auth0-live-validation": _validate_auth0,
        "isolated-restore-rehearsal": _validate_restore,
        "deletion-boundary-rehearsal": _validate_deletion,
        "runtime-secret-rotation": _validate_rotation,
        "prior-worker-session-revocation": _validate_prior_roles,
    }
    try:
        validator = validators[evidence_type]
    except KeyError as error:
        raise EvidenceSemanticsError(
            f"Unsupported external evidence type: {evidence_type}."
        ) from error
    validator(results)


def _validate_auth0(results: Mapping[str, Any]) -> None:
    _exact_keys(
        results,
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
        },
        "Auth0 observation",
    )
    for name in ("issuer_url", "callback_url"):
        value = results[name]
        if not isinstance(value, str) or not 1 <= len(value) <= 2048:
            raise EvidenceSemanticsError(f"Auth0 result {name} is not a bounded URL.")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise EvidenceSemanticsError(
                f"Auth0 result {name} must be a credential-free HTTPS URL."
            )
    issuer = urlsplit(str(results["issuer_url"]))
    callback = urlsplit(str(results["callback_url"]))
    if issuer.path != "/" or not str(results["issuer_url"]).endswith("/"):
        raise EvidenceSemanticsError("Auth0 issuer URL must be the exact tenant origin.")
    if callback.path != "/api/auth/callback":
        raise EvidenceSemanticsError("Auth0 callback URL must use the exact route.")
    request_names = (
        "authorization_request_id",
        "allowlisted_callback_request_id",
        "unallowlisted_callback_request_id",
        "logout_request_id",
        "revoked_session_request_id",
    )
    for name in request_names:
        _uuid(results.get(name), f"Auth0 {name}")
    if len({results[name] for name in request_names}) != len(request_names):
        raise EvidenceSemanticsError("Auth0 observations require distinct request IDs.")
    exact = {
        "authorization_code_challenge_method": "S256",
        "authorization_response_type": "code",
        "allowlisted_callback_status_code": 303,
        "unallowlisted_callback_status_code": 403,
        "logout_status_code": 204,
        "revoked_session_status_code": 401,
    }
    if any(results.get(name) != value for name, value in exact.items()):
        raise EvidenceSemanticsError("Auth0 observations do not prove the exact safe flow.")


def _validate_restore(results: Mapping[str, Any]) -> None:
    _exact_keys(
        results,
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
        },
        "isolated restore",
    )
    source = results["source_identifier"]
    target = results["target_identifier"]
    if (
        not isinstance(source, str)
        or _IDENTIFIER.fullmatch(source) is None
        or not isinstance(target, str)
        or _IDENTIFIER.fullmatch(target) is None
        or source == target
    ):
        raise EvidenceSemanticsError("Restore source and target must be distinct identifiers.")
    if results["database_role"] != "ai_fde_app":
        raise EvidenceSemanticsError("Restore must use the application database role.")
    _uuid(results.get("audit_event_id"), "Restore audit event")
    _uuid(results.get("digest_subject_id"), "Restore digest subject")
    if results["digest_subject_type"] not in {
        "deployment-package",
        "implementation-artifact",
    }:
        raise EvidenceSemanticsError("Restore digest subject type is unsupported.")
    for name in ("audit_fingerprint", "stored_digest", "row_fingerprint"):
        if not isinstance(results[name], str) or _DIGEST.fullmatch(results[name]) is None:
            raise EvidenceSemanticsError(f"Restore {name} is not an exact digest.")
    if any(
        results.get(name) is not True
        for name in ("source_target_isolated", "durable_record_matched", "digest_matched")
    ):
        raise EvidenceSemanticsError("Restore observations do not prove an isolated match.")


def _validate_deletion(results: Mapping[str, Any]) -> None:
    _exact_keys(
        results,
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
        },
        "deletion boundary observation",
    )
    engagement = _uuid(results.get("engagement_id"), "Deletion engagement")
    _uuid(results.get("deletion_receipt_id"), "Deletion receipt")
    control = _uuid(results.get("control_engagement_id"), "Deletion control")
    if engagement == control:
        raise EvidenceSemanticsError("Deletion control engagement must be distinct.")
    for name in (
        "application_rows_remaining",
        "current_objects_remaining",
        "object_versions_remaining",
        "delete_markers_remaining",
    ):
        if type(results[name]) is not int or results[name] != 0:
            raise EvidenceSemanticsError(f"Deletion {name} must be integer zero.")
    for name in ("object_versions_deleted", "delete_markers_deleted"):
        if type(results[name]) is not int or results[name] < 0:
            raise EvidenceSemanticsError(f"Deletion {name} must be nonnegative.")
    before = results["control_fingerprint_before"]
    after = results["control_fingerprint_after"]
    if (
        not isinstance(before, str)
        or _DIGEST.fullmatch(before) is None
        or not isinstance(after, str)
        or _DIGEST.fullmatch(after) is None
        or not hmac.compare_digest(before, after)
    ):
        raise EvidenceSemanticsError("Deletion changed the control fingerprint.")
    deleted_at = _timestamp(results.get("deletion_completed_at"), "Deletion completion")
    expiry = _timestamp(results.get("backup_expiry_at"), "Deletion backup expiry")
    rds_days = results["rds_backup_retention_days"]
    s3_days = results["s3_noncurrent_retention_days"]
    if type(rds_days) is not int or not 1 <= rds_days <= 35:
        raise EvidenceSemanticsError("RDS backup retention must be 1-35 days.")
    if type(s3_days) is not int or not 7 <= s3_days <= 90:
        raise EvidenceSemanticsError("S3 noncurrent retention must be 7-90 days.")
    if expiry != deleted_at + timedelta(days=rds_days):
        raise EvidenceSemanticsError("Deletion backup expiry is not RDS-derived.")


def _validate_rotation(results: Mapping[str, Any]) -> None:
    _exact_keys(
        results,
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
        },
        "runtime secret rotation",
    )
    for name in ("api_secret_arn", "migration_secret_arn"):
        value = results[name]
        if not isinstance(value, str) or _SECRET_ARN.fullmatch(value) is None or "*" in value:
            raise EvidenceSemanticsError(f"Rotation {name} is not an exact secret ARN.")
    if results["api_secret_arn"] == results["migration_secret_arn"]:
        raise EvidenceSemanticsError("Rotation secrets must remain role-separated.")
    for prefix in ("api", "migration"):
        previous = results[f"{prefix}_previous_version_id"]
        current = results[f"{prefix}_current_version_id"]
        if (
            not isinstance(previous, str)
            or _VERSION_ID.fullmatch(previous) is None
            or not isinstance(current, str)
            or _VERSION_ID.fullmatch(current) is None
            or previous == current
        ):
            raise EvidenceSemanticsError("Rotation requires distinct exact secret versions.")
    if results["old_api_login_sqlstate"] not in {"28000", "28P01"}:
        raise EvidenceSemanticsError("Rotation did not prove old-login authentication denial.")
    if (
        results["worker_group_role"] != "ai_fde_worker"
        or results["worker_group_login_state"] != "NOLOGIN"
    ):
        raise EvidenceSemanticsError("Worker privilege group is not NOLOGIN.")
    retired = results["retired_worker_database_user"]
    current = results["current_worker_database_user"]
    if (
        not isinstance(retired, str)
        or _WORKER_USER.fullmatch(retired) is None
        or not isinstance(current, str)
        or _WORKER_USER.fullmatch(current) is None
        or retired == current
    ):
        raise EvidenceSemanticsError("Worker logins are not distinct release identities.")
    if (
        type(results["prior_worker_sessions_remaining"]) is not int
        or results["prior_worker_sessions_remaining"] != 0
    ):
        raise EvidenceSemanticsError("Prior worker database sessions remain active.")
    _timestamp(results.get("rotation_completed_at"), "Rotation completion")


def _validate_prior_roles(results: Mapping[str, Any]) -> None:
    _exact_keys(results, {"roles"}, "prior worker session revocation")
    roles = results["roles"]
    if not isinstance(roles, list) or len(roles) > 20:
        raise EvidenceSemanticsError("Prior worker role list is invalid.")
    expected_keys = {
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
        if not isinstance(role, dict) or set(role) != expected_keys:
            raise EvidenceSemanticsError("Prior worker role schema is invalid.")
        role_arn = role["role_arn"]
        revision = role["prior_release_revision"]
        deployment_id = role["prior_deployment_id"]
        if (
            not isinstance(role_arn, str)
            or _ROLE_ARN.fullmatch(role_arn) is None
            or "*" in role_arn
            or not isinstance(revision, str)
            or _REVISION.fullmatch(revision) is None
            or revision == "0" * 40
            or not isinstance(deployment_id, str)
            or _IDENTIFIER.fullmatch(deployment_id) is None
        ):
            raise EvidenceSemanticsError("Prior worker release identity is invalid.")
        role_arns.append(role_arn)
        state = role["identity_state"]
        if (
            state not in {"retained-quarantined", "deleted-after-ttl"}
            or role["quarantine_control"] != "inline-deny-pre-cutoff-sessions"
            or role["assume_role_disabled"] is not True
            or role["permission_grants_stripped"] is not True
            or not isinstance(role["quarantine_policy_digest"], str)
            or _DIGEST.fullmatch(role["quarantine_policy_digest"]) is None
        ):
            raise EvidenceSemanticsError("Prior worker quarantine claims are invalid.")
        max_session = role["max_session_duration_seconds"]
        propagation = role["propagation_wait_seconds"]
        if (
            type(max_session) is not int
            or not 900 <= max_session <= 43200
            or type(propagation) is not int
            or not 60 <= propagation <= 3600
        ):
            raise EvidenceSemanticsError("Prior worker session boundary is invalid.")
        applied = _timestamp(role["quarantine_applied_at"], "Quarantine application")
        cutoff = _timestamp(role["revocation_cutoff_at"], "Revocation cutoff")
        issued = _timestamp(role["captured_session_issued_at"], "Session issuance")
        expires = _timestamp(role["captured_session_expires_at"], "Session expiry")
        probe = _timestamp(role["live_probe_completed_at"], "Live probe")
        expiry_boundary = _timestamp(
            role["session_expiry_not_before"], "Session expiry boundary"
        )
        if (
            applied > cutoff
            or issued >= cutoff
            or expires <= issued
            or expires > issued + timedelta(seconds=max_session)
            or probe >= expires
            or probe < cutoff + timedelta(seconds=propagation)
            or expiry_boundary != cutoff + timedelta(seconds=max_session + propagation)
        ):
            raise EvidenceSemanticsError("Prior worker session revocation timing is invalid.")
        deleted = role["deleted_at"]
        if state == "retained-quarantined" and deleted is not None:
            raise EvidenceSemanticsError("Retained prior worker role claims deletion.")
        if state == "deleted-after-ttl":
            deleted_at = _timestamp(deleted, "Prior role deletion")
            if deleted_at < expiry_boundary or deleted_at < probe:
                raise EvidenceSemanticsError("Prior worker role was deleted before TTL settled.")
        targets = role["targets"]
        probes = role["probe_results"]
        if not isinstance(targets, dict) or set(targets) != target_keys:
            raise EvidenceSemanticsError("Prior worker probe targets are invalid.")
        if (
            not isinstance(probes, dict)
            or set(probes) != probe_keys
            or any(decision != "denied" for decision in probes.values())
        ):
            raise EvidenceSemanticsError("Prior worker probes do not all prove denial.")
        for name, target in targets.items():
            if not isinstance(target, str) or not 20 <= len(target) <= 1024:
                raise EvidenceSemanticsError("Prior worker probe target is invalid.")
            if name == "s3_object_prefix_arn":
                if not target.endswith("/*") or "*" in target[:-1]:
                    raise EvidenceSemanticsError("Prior worker S3 prefix is not exact.")
            elif "*" in target:
                raise EvidenceSemanticsError("Prior worker probe target is not exact.")
    if role_arns != sorted(set(role_arns)):
        raise EvidenceSemanticsError("Prior worker roles are not sorted and unique.")


def _exact_keys(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise EvidenceSemanticsError(f"{label} results do not match the mandatory schema.")


def _uuid(value: object, label: str) -> uuid.UUID:
    try:
        parsed = uuid.UUID(value) if isinstance(value, str) else None
    except ValueError as error:
        raise EvidenceSemanticsError(f"{label} is not a canonical UUID.") from error
    if parsed is None or str(parsed) != value or parsed.int == 0:
        raise EvidenceSemanticsError(f"{label} is not a nonzero canonical UUID.")
    return parsed


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not 20 <= len(value) <= 40:
        raise EvidenceSemanticsError(f"{label} is not a bounded timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceSemanticsError(f"{label} is not ISO-8601.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceSemanticsError(f"{label} must include a timezone.")
    return parsed.astimezone(UTC)
