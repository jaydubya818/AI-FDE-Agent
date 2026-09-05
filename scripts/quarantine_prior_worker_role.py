from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn, cast
from urllib.parse import unquote

from botocore.exceptions import BotoCoreError, ClientError

from scripts.qualification_evidence import (
    EvidenceRecordError,
    load_and_validate_evidence_record,
)

RECEIPT_SCHEMA_VERSION = "ai-fde.prior-worker-quarantine/v1"
QUARANTINE_CONTROL = "inline-deny-pre-cutoff-sessions"
QUARANTINE_POLICY_NAME = "AWSRevokeOlderSessions"
MAX_IAM_LIST_ITEMS = 100
MAX_IAM_LIST_PAGES = 20
DEFAULT_PROPAGATION_WAIT_SECONDS = 300
DEFAULT_MAXIMUM_PROBE_AGE_SECONDS = 900

_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
_DEPLOYMENT_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{7,119}")
_ROLE_ARN_PATTERN = re.compile(
    r"arn:(aws|aws-us-gov|aws-cn|aws-iso|aws-iso-b):iam::([0-9]{12}):"
    r"role/([A-Za-z0-9+=,.@_/-]{1,512})"
)

_DISABLED_ASSUME_ROLE_POLICY: dict[str, object] = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AIFDEQuarantineDenyAssumeRole",
            "Effect": "Deny",
            "Principal": {"AWS": "*"},
            "Action": "sts:AssumeRole",
        }
    ],
}


class PriorWorkerRoleError(RuntimeError):
    """Base class for fail-closed prior-worker quarantine errors."""


class PriorWorkerRoleNotFoundError(PriorWorkerRoleError):
    """The exact prior worker role or one of its required controls does not exist."""


class PriorWorkerRoleAccessDeniedError(PriorWorkerRoleError):
    """AWS denied an IAM operation required to prove or change quarantine state."""


class PriorWorkerRoleAPIError(PriorWorkerRoleError):
    """AWS returned an unexpected or malformed IAM response."""


def verify_live_prior_worker_quarantine(
    iam_client: Any,
    *,
    role_arn: str,
    prior_release_revision: str,
    prior_deployment_id: str,
    current_release_revision: str,
    current_deployment_id: str,
    expected_policy_digest: str,
    expected_cutoff_at: str,
    expected_max_session_duration: int,
) -> dict[str, object]:
    """Read and prove the complete fail-closed state of one retained prior role."""

    role_name = _validate_release_binding(
        role_arn=role_arn,
        prior_release_revision=prior_release_revision,
        prior_deployment_id=prior_deployment_id,
        current_release_revision=current_release_revision,
        current_deployment_id=current_deployment_id,
    )
    if not isinstance(expected_policy_digest, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", expected_policy_digest
    ):
        raise PriorWorkerRoleError("Expected quarantine policy digest is invalid.")
    if (
        type(expected_max_session_duration) is not int
        or not 900 <= expected_max_session_duration <= 43200
    ):
        raise PriorWorkerRoleError("Expected role maximum session duration is invalid.")
    cutoff = _parse_time(expected_cutoff_at, "Expected revocation cutoff")
    _verify_live_quarantine(
        iam_client,
        role_name=role_name,
        role_arn=role_arn,
        expected_policy_digest=expected_policy_digest,
        expected_cutoff=cutoff,
        expected_max_session_duration=expected_max_session_duration,
    )
    return {
        "quarantine_control": QUARANTINE_CONTROL,
        "quarantine_policy_name": QUARANTINE_POLICY_NAME,
        "quarantine_policy_digest": expected_policy_digest,
        "revocation_cutoff_at": _format_time(cutoff),
        "max_session_duration_seconds": expected_max_session_duration,
        "assume_role_disabled": True,
        "sole_inline_policy": True,
        "attached_managed_policy_count": 0,
        "permissions_boundary_present": False,
        "instance_profile_count": 0,
    }


def quarantine_prior_worker_role(
    iam_client: Any,
    *,
    role_arn: str,
    prior_release_revision: str,
    prior_deployment_id: str,
    current_release_revision: str,
    current_deployment_id: str,
    captured_session_issued_at: datetime,
    captured_session_expires_at: datetime,
    propagation_wait_seconds: int = DEFAULT_PROPAGATION_WAIT_SECONDS,
    now: datetime | None = None,
) -> dict[str, object]:
    """Quarantine one release-bound worker role and return non-secret observations."""

    role_name = _validate_release_binding(
        role_arn=role_arn,
        prior_release_revision=prior_release_revision,
        prior_deployment_id=prior_deployment_id,
        current_release_revision=current_release_revision,
        current_deployment_id=current_deployment_id,
    )
    if not 60 <= propagation_wait_seconds <= 3600:
        raise PriorWorkerRoleError("IAM propagation wait must be between 60 and 3600 seconds.")
    cutoff = _decision_time(now)
    captured_at = _require_utc_datetime(
        captured_session_issued_at, "Captured prior-worker session issuance"
    )
    if captured_at >= cutoff:
        raise PriorWorkerRoleError(
            "Captured prior-worker session issuance must be earlier than the revocation cutoff."
        )

    role = _get_exact_role(iam_client, role_name=role_name, role_arn=role_arn)
    max_session_duration = _max_session_duration(role)
    captured_expires_at = _require_utc_datetime(
        captured_session_expires_at, "Captured prior-worker session expiry"
    )
    propagation_deadline = cutoff + timedelta(seconds=propagation_wait_seconds)
    if captured_expires_at <= propagation_deadline:
        raise PriorWorkerRoleError(
            "Captured prior-worker session must remain live beyond IAM propagation."
        )
    if captured_expires_at > captured_at + timedelta(seconds=max_session_duration):
        raise PriorWorkerRoleError(
            "Captured prior-worker session expiry exceeds the role maximum session duration."
        )
    quarantine_policy = _quarantine_policy(cutoff)
    quarantine_policy_digest = _policy_digest(quarantine_policy)

    _iam_call(
        "PutRolePolicy",
        iam_client.put_role_policy,
        RoleName=role_name,
        PolicyName=QUARANTINE_POLICY_NAME,
        PolicyDocument=_canonical_json(quarantine_policy),
    )
    _iam_call(
        "UpdateAssumeRolePolicy",
        iam_client.update_assume_role_policy,
        RoleName=role_name,
        PolicyDocument=_canonical_json(_DISABLED_ASSUME_ROLE_POLICY),
    )
    stripped_counts = _strip_role_grants(iam_client, role_name=role_name)

    _verify_live_quarantine(
        iam_client,
        role_name=role_name,
        role_arn=role_arn,
        expected_policy_digest=quarantine_policy_digest,
        expected_cutoff=cutoff,
        expected_max_session_duration=max_session_duration,
    )
    session_expiry = propagation_deadline + timedelta(seconds=max_session_duration)
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "action": "quarantine",
        "status": "quarantined",
        "role_arn": role_arn,
        "prior_release_revision": prior_release_revision,
        "prior_deployment_id": prior_deployment_id,
        "quarantine_control": QUARANTINE_CONTROL,
        "quarantine_policy_name": QUARANTINE_POLICY_NAME,
        "quarantine_policy_digest": quarantine_policy_digest,
        "assume_role_disabled": True,
        "permission_grants_stripped": True,
        "quarantine_applied_at": _format_time(cutoff),
        "revocation_cutoff_at": _format_time(cutoff),
        "propagation_deadline_at": _format_time(propagation_deadline),
        "session_expiry_not_before": _format_time(session_expiry),
        "max_session_duration_seconds": max_session_duration,
        "propagation_wait_seconds": propagation_wait_seconds,
        "captured_session_issued_at": _format_time(captured_at),
        "captured_session_expires_at": _format_time(captured_expires_at),
        "stripped_grant_counts": stripped_counts,
    }


def verify_prior_worker_state_rm(
    iam_client: Any,
    kms_client: Any,
    *,
    evidence_record: Path,
    role_arn: str,
    prior_release_revision: str,
    prior_deployment_id: str,
    current_release_revision: str,
    current_deployment_id: str,
    evidence_issuer_role_arn: str,
    evidence_signing_key_arn: str,
    expected_targets: Mapping[str, str],
    maximum_evidence_age_days: int = 30,
    maximum_probe_age_seconds: int = DEFAULT_MAXIMUM_PROBE_AGE_SECONDS,
    now: datetime | None = None,
) -> dict[str, object]:
    """Authorize, but never perform, state removal for an exactly quarantined role."""

    role_name = _validate_release_binding(
        role_arn=role_arn,
        prior_release_revision=prior_release_revision,
        prior_deployment_id=prior_deployment_id,
        current_release_revision=current_release_revision,
        current_deployment_id=current_deployment_id,
    )
    reference_time = _decision_time(now)
    role_observation, evidence_digest = _authenticated_role_observation(
        kms_client,
        evidence_record=evidence_record,
        role_arn=role_arn,
        prior_release_revision=prior_release_revision,
        prior_deployment_id=prior_deployment_id,
        current_release_revision=current_release_revision,
        current_deployment_id=current_deployment_id,
        evidence_issuer_role_arn=evidence_issuer_role_arn,
        evidence_signing_key_arn=evidence_signing_key_arn,
        expected_targets=expected_targets,
        maximum_evidence_age_days=maximum_evidence_age_days,
        maximum_probe_age_seconds=maximum_probe_age_seconds,
        now=reference_time,
    )
    if role_observation["identity_state"] != "retained-quarantined":
        raise PriorWorkerRoleError(
            "State removal requires signed retained-quarantined role evidence."
        )
    propagation_deadline = _propagation_deadline(role_observation)
    if reference_time < propagation_deadline:
        raise PriorWorkerRoleError("IAM propagation has not reached the signed wait boundary.")
    _verify_live_quarantine(
        iam_client,
        role_name=role_name,
        role_arn=role_arn,
        expected_policy_digest=cast(str, role_observation["quarantine_policy_digest"]),
        expected_cutoff=_parse_time(
            role_observation["revocation_cutoff_at"], "Signed revocation cutoff"
        ),
        expected_max_session_duration=cast(
            int, role_observation["max_session_duration_seconds"]
        ),
    )
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "action": "verify-state-rm",
        "status": "authorized",
        "authorized": True,
        "role_arn": role_arn,
        "prior_release_revision": prior_release_revision,
        "prior_deployment_id": prior_deployment_id,
        "evidence_content_digest": evidence_digest,
        "quarantine_policy_digest": role_observation["quarantine_policy_digest"],
        "revocation_cutoff_at": role_observation["revocation_cutoff_at"],
        "propagation_deadline_at": _format_time(propagation_deadline),
        "verified_at": _format_time(reference_time),
    }


def cleanup_prior_worker_role(
    iam_client: Any,
    kms_client: Any,
    *,
    evidence_record: Path,
    role_arn: str,
    prior_release_revision: str,
    prior_deployment_id: str,
    current_release_revision: str,
    current_deployment_id: str,
    evidence_issuer_role_arn: str,
    evidence_signing_key_arn: str,
    expected_targets: Mapping[str, str],
    maximum_evidence_age_days: int = 30,
    now: datetime | None = None,
) -> dict[str, object]:
    """Delete a quarantined role only after authenticated probes and the exact TTL boundary."""

    role_name = _validate_release_binding(
        role_arn=role_arn,
        prior_release_revision=prior_release_revision,
        prior_deployment_id=prior_deployment_id,
        current_release_revision=current_release_revision,
        current_deployment_id=current_deployment_id,
    )
    reference_time = _decision_time(now)
    role_observation, evidence_digest = _authenticated_role_observation(
        kms_client,
        evidence_record=evidence_record,
        role_arn=role_arn,
        prior_release_revision=prior_release_revision,
        prior_deployment_id=prior_deployment_id,
        current_release_revision=current_release_revision,
        current_deployment_id=current_deployment_id,
        evidence_issuer_role_arn=evidence_issuer_role_arn,
        evidence_signing_key_arn=evidence_signing_key_arn,
        expected_targets=expected_targets,
        maximum_evidence_age_days=maximum_evidence_age_days,
        maximum_probe_age_seconds=None,
        now=reference_time,
    )
    session_expiry = _parse_time(
        role_observation["session_expiry_not_before"], "Signed session-expiry boundary"
    )
    if reference_time < session_expiry:
        raise PriorWorkerRoleError(
            "Prior worker role cleanup is forbidden before session TTL and propagation settle."
        )

    signed_deleted = role_observation["identity_state"] == "deleted-after-ttl"
    try:
        _get_exact_role(iam_client, role_name=role_name, role_arn=role_arn)
    except PriorWorkerRoleNotFoundError:
        already_deleted = True
    else:
        already_deleted = False
        if signed_deleted:
            raise PriorWorkerRoleError(
                "Signed deleted role evidence conflicts with the live IAM role."
            )
        _verify_live_quarantine(
            iam_client,
            role_name=role_name,
            role_arn=role_arn,
            expected_policy_digest=cast(str, role_observation["quarantine_policy_digest"]),
            expected_cutoff=_parse_time(
                role_observation["revocation_cutoff_at"], "Signed revocation cutoff"
            ),
            expected_max_session_duration=cast(
                int, role_observation["max_session_duration_seconds"]
            ),
        )
    if not already_deleted:
        with suppress(PriorWorkerRoleNotFoundError):
            _iam_call(
                "DeleteRolePolicy",
                iam_client.delete_role_policy,
                RoleName=role_name,
                PolicyName=QUARANTINE_POLICY_NAME,
            )
        try:
            _iam_call("DeleteRole", iam_client.delete_role, RoleName=role_name)
        except PriorWorkerRoleNotFoundError:
            already_deleted = True
        except PriorWorkerRoleError:
            _restore_quarantine_policy(
                iam_client,
                role_name=role_name,
                cutoff=_parse_time(
                    role_observation["revocation_cutoff_at"],
                    "Signed revocation cutoff",
                ),
            )
            raise
        if not already_deleted:
            try:
                _get_exact_role(iam_client, role_name=role_name, role_arn=role_arn)
            except PriorWorkerRoleNotFoundError:
                pass
            else:
                _restore_quarantine_policy(
                    iam_client,
                    role_name=role_name,
                    cutoff=_parse_time(
                        role_observation["revocation_cutoff_at"],
                        "Signed revocation cutoff",
                    ),
                )
                raise PriorWorkerRoleAPIError(
                    "DeleteRole returned without proving that the exact role was deleted."
                )

    deleted_at = (
        role_observation["deleted_at"]
        if signed_deleted
        else _format_time(reference_time)
    )
    deleted_observation = dict(role_observation)
    deleted_observation["identity_state"] = "deleted-after-ttl"
    deleted_observation["deleted_at"] = deleted_at
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "action": "cleanup",
        "status": "already-deleted" if already_deleted else "deleted",
        "role_arn": role_arn,
        "evidence_content_digest": evidence_digest,
        "deleted_at": deleted_at,
        "sealable_observations": {"roles": [deleted_observation]},
    }


def _authenticated_role_observation(
    kms_client: Any,
    *,
    evidence_record: Path,
    role_arn: str,
    prior_release_revision: str,
    prior_deployment_id: str,
    current_release_revision: str,
    current_deployment_id: str,
    evidence_issuer_role_arn: str,
    evidence_signing_key_arn: str,
    expected_targets: Mapping[str, str],
    maximum_evidence_age_days: int,
    maximum_probe_age_seconds: int | None,
    now: datetime,
) -> tuple[dict[str, object], str]:
    if maximum_probe_age_seconds is not None and not 60 <= maximum_probe_age_seconds <= 86400:
        raise PriorWorkerRoleError("Live probe age must be between 60 and 86400 seconds.")
    expected_target_keys = {
        "db_user_arn",
        "s3_object_prefix_arn",
        "kms_key_arn",
        "bedrock_model_arn",
    }
    if set(expected_targets) != expected_target_keys:
        raise PriorWorkerRoleError("Expected live-probe targets do not match the exact schema.")
    evidence = load_and_validate_evidence_record(
        evidence_record,
        expected_type="prior-worker-session-revocation",
        expected_revision=current_release_revision,
        expected_deployment_id=current_deployment_id,
        expected_issuer_role_arn=evidence_issuer_role_arn,
        expected_signing_key_arn=evidence_signing_key_arn,
        kms_client=kms_client,
        maximum_age_days=maximum_evidence_age_days,
        now=now,
    )
    signed_record = evidence.get("signed_record")
    if not isinstance(signed_record, dict):
        raise PriorWorkerRoleError("Authenticated evidence omitted its signed record.")
    results = signed_record.get("results")
    roles = results.get("roles") if isinstance(results, dict) else None
    if not isinstance(roles, list):
        raise PriorWorkerRoleError("Authenticated evidence omitted prior-worker roles.")
    matching_roles = [
        role
        for role in roles
        if isinstance(role, dict)
        and role.get("role_arn") == role_arn
        and role.get("prior_release_revision") == prior_release_revision
        and role.get("prior_deployment_id") == prior_deployment_id
    ]
    if len(matching_roles) != 1:
        raise PriorWorkerRoleError(
            "Authenticated evidence does not contain the exact prior release role once."
        )
    observation = cast(dict[str, object], matching_roles[0])
    if observation.get("targets") != dict(expected_targets):
        raise PriorWorkerRoleError(
            "Authenticated denied probes are not bound to the exact current targets."
        )
    probe_results = observation.get("probe_results")
    if not isinstance(probe_results, dict) or any(
        result != "denied" for result in probe_results.values()
    ):
        raise PriorWorkerRoleError("Authenticated live probe results are not all denied.")
    probe_completed_at = _parse_time(
        observation.get("live_probe_completed_at"), "Signed live-probe completion"
    )
    captured_issued_at = _parse_time(
        observation.get("captured_session_issued_at"),
        "Signed captured-session issuance",
    )
    captured_expires_at = _parse_time(
        observation.get("captured_session_expires_at"),
        "Signed captured-session expiry",
    )
    cutoff = _parse_time(
        observation.get("revocation_cutoff_at"), "Signed revocation cutoff"
    )
    max_session_duration = observation.get("max_session_duration_seconds")
    if (
        type(max_session_duration) is not int
        or captured_issued_at >= cutoff
        or not captured_issued_at < probe_completed_at < captured_expires_at
        or captured_expires_at
        > captured_issued_at + timedelta(seconds=max_session_duration)
    ):
        raise PriorWorkerRoleError(
            "Signed denied probes were not captured with the live pre-cutoff session."
        )
    if probe_completed_at > now:
        raise PriorWorkerRoleError("Signed live probes cannot complete in the future.")
    completed_at = _parse_time(evidence.get("completed_at"), "Authenticated evidence completion")
    if probe_completed_at > completed_at:
        raise PriorWorkerRoleError("Signed live probes cannot follow evidence completion.")
    if (
        maximum_probe_age_seconds is not None
        and probe_completed_at < now - timedelta(seconds=maximum_probe_age_seconds)
    ):
        raise PriorWorkerRoleError("Signed live denied probes are no longer current.")
    content_digest = evidence.get("content_digest")
    if not isinstance(content_digest, str):
        raise PriorWorkerRoleError("Authenticated evidence omitted its content digest.")
    return observation, content_digest


def _verify_live_quarantine(
    iam_client: Any,
    *,
    role_name: str,
    role_arn: str,
    expected_policy_digest: str,
    expected_cutoff: datetime,
    expected_max_session_duration: int,
) -> None:
    role = _get_exact_role(iam_client, role_name=role_name, role_arn=role_arn)
    if _max_session_duration(role) != expected_max_session_duration:
        raise PriorWorkerRoleError(
            "Live role maximum session duration differs from signed evidence."
        )
    trust_policy = _decode_policy_document(
        role.get("AssumeRolePolicyDocument"), "Live assume-role policy"
    )
    if trust_policy != _DISABLED_ASSUME_ROLE_POLICY:
        raise PriorWorkerRoleError("Live role assumption is not exactly disabled.")
    if role.get("PermissionsBoundary") is not None:
        raise PriorWorkerRoleError("Live role still has a permissions boundary grant.")

    attached = _list_iam_items(
        iam_client,
        method_name="list_attached_role_policies",
        operation="ListAttachedRolePolicies",
        result_key="AttachedPolicies",
        role_name=role_name,
    )
    if attached:
        raise PriorWorkerRoleError("Live role still has attached managed policies.")
    profiles = _list_iam_items(
        iam_client,
        method_name="list_instance_profiles_for_role",
        operation="ListInstanceProfilesForRole",
        result_key="InstanceProfiles",
        role_name=role_name,
    )
    if profiles:
        raise PriorWorkerRoleError("Live role still has instance-profile bindings.")
    inline_names = _list_iam_items(
        iam_client,
        method_name="list_role_policies",
        operation="ListRolePolicies",
        result_key="PolicyNames",
        role_name=role_name,
    )
    if inline_names != [QUARANTINE_POLICY_NAME]:
        raise PriorWorkerRoleError("Live role has an unexpected inline permission policy.")
    response = _iam_call(
        "GetRolePolicy",
        iam_client.get_role_policy,
        RoleName=role_name,
        PolicyName=QUARANTINE_POLICY_NAME,
    )
    policy = _decode_policy_document(response.get("PolicyDocument"), "Live quarantine policy")
    if _policy_digest(policy) != expected_policy_digest:
        raise PriorWorkerRoleError("Live quarantine policy differs from signed evidence.")
    if _quarantine_policy_cutoff(policy) != expected_cutoff:
        raise PriorWorkerRoleError("Live quarantine cutoff differs from signed evidence.")


def _restore_quarantine_policy(
    iam_client: Any, *, role_name: str, cutoff: datetime
) -> None:
    """Restore the sole delete prerequisite when DeleteRole did not complete."""

    _iam_call(
        "PutRolePolicy",
        iam_client.put_role_policy,
        RoleName=role_name,
        PolicyName=QUARANTINE_POLICY_NAME,
        PolicyDocument=_canonical_json(_quarantine_policy(cutoff)),
    )


def _strip_role_grants(iam_client: Any, *, role_name: str) -> dict[str, int]:
    attached = _list_iam_items(
        iam_client,
        method_name="list_attached_role_policies",
        operation="ListAttachedRolePolicies",
        result_key="AttachedPolicies",
        role_name=role_name,
    )
    detached = 0
    for item in attached:
        if not isinstance(item, dict) or not isinstance(item.get("PolicyArn"), str):
            raise PriorWorkerRoleAPIError("ListAttachedRolePolicies returned a malformed policy.")
        with suppress(PriorWorkerRoleNotFoundError):
            _iam_call(
                "DetachRolePolicy",
                iam_client.detach_role_policy,
                RoleName=role_name,
                PolicyArn=item["PolicyArn"],
            )
        detached += 1

    inline_names = _list_iam_items(
        iam_client,
        method_name="list_role_policies",
        operation="ListRolePolicies",
        result_key="PolicyNames",
        role_name=role_name,
    )
    deleted_inline = 0
    for policy_name in inline_names:
        if not isinstance(policy_name, str) or not 1 <= len(policy_name) <= 128:
            raise PriorWorkerRoleAPIError("ListRolePolicies returned a malformed policy name.")
        if policy_name == QUARANTINE_POLICY_NAME:
            continue
        with suppress(PriorWorkerRoleNotFoundError):
            _iam_call(
                "DeleteRolePolicy",
                iam_client.delete_role_policy,
                RoleName=role_name,
                PolicyName=policy_name,
            )
        deleted_inline += 1

    role = _get_role(iam_client, role_name=role_name)
    boundary_removed = 0
    if role.get("PermissionsBoundary") is not None:
        with suppress(PriorWorkerRoleNotFoundError):
            _iam_call(
                "DeleteRolePermissionsBoundary",
                iam_client.delete_role_permissions_boundary,
                RoleName=role_name,
            )
        boundary_removed = 1

    profiles = _list_iam_items(
        iam_client,
        method_name="list_instance_profiles_for_role",
        operation="ListInstanceProfilesForRole",
        result_key="InstanceProfiles",
        role_name=role_name,
    )
    removed_profiles = 0
    for item in profiles:
        if not isinstance(item, dict) or not isinstance(item.get("InstanceProfileName"), str):
            raise PriorWorkerRoleAPIError(
                "ListInstanceProfilesForRole returned a malformed profile."
            )
        with suppress(PriorWorkerRoleNotFoundError):
            _iam_call(
                "RemoveRoleFromInstanceProfile",
                iam_client.remove_role_from_instance_profile,
                InstanceProfileName=item["InstanceProfileName"],
                RoleName=role_name,
            )
        removed_profiles += 1
    return {
        "attached_managed_policies": detached,
        "inline_policies": deleted_inline,
        "permissions_boundaries": boundary_removed,
        "instance_profile_bindings": removed_profiles,
    }


def _list_iam_items(
    iam_client: Any,
    *,
    method_name: str,
    operation: str,
    result_key: str,
    role_name: str,
) -> list[object]:
    method = cast(Callable[..., object], getattr(iam_client, method_name))
    items: list[object] = []
    marker: str | None = None
    seen_markers: set[str] = set()
    for _ in range(MAX_IAM_LIST_PAGES):
        request: dict[str, object] = {"RoleName": role_name}
        if marker is not None:
            request["Marker"] = marker
        response = _iam_call(operation, method, **request)
        page = response.get(result_key)
        if not isinstance(page, list):
            raise PriorWorkerRoleAPIError(f"{operation} returned a malformed item list.")
        items.extend(page)
        if len(items) > MAX_IAM_LIST_ITEMS:
            raise PriorWorkerRoleAPIError(f"{operation} exceeded its bounded item limit.")
        if response.get("IsTruncated") is not True:
            if response.get("IsTruncated") not in (False, None):
                raise PriorWorkerRoleAPIError(f"{operation} returned malformed pagination state.")
            return items
        next_marker = response.get("Marker")
        if (
            not isinstance(next_marker, str)
            or not next_marker
            or next_marker in seen_markers
        ):
            raise PriorWorkerRoleAPIError(f"{operation} returned an invalid pagination marker.")
        seen_markers.add(next_marker)
        marker = next_marker
    raise PriorWorkerRoleAPIError(f"{operation} exceeded its bounded page limit.")


def _iam_call(
    operation: str, method: Callable[..., object], **request: object
) -> dict[str, object]:
    try:
        response = method(**request)
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        if error_code in {"NoSuchEntity", "NoSuchEntityException"}:
            raise PriorWorkerRoleNotFoundError(
                f"AWS IAM {operation} returned NoSuchEntity."
            ) from error
        if error_code in {
            "AccessDenied",
            "AccessDeniedException",
            "UnauthorizedOperation",
        }:
            raise PriorWorkerRoleAccessDeniedError(
                f"AWS IAM {operation} returned AccessDenied."
            ) from error
        bounded_code = (
            error_code
            if isinstance(error_code, str) and len(error_code) <= 80
            else "Error"
        )
        raise PriorWorkerRoleAPIError(
            f"AWS IAM {operation} failed with {bounded_code}."
        ) from error
    except BotoCoreError as error:
        raise PriorWorkerRoleAPIError(f"AWS IAM {operation} could not complete.") from error
    if response is None:
        return {}
    if not isinstance(response, dict):
        raise PriorWorkerRoleAPIError(f"AWS IAM {operation} returned a malformed response.")
    return cast(dict[str, object], response)


def _get_role(iam_client: Any, *, role_name: str) -> dict[str, object]:
    response = _iam_call("GetRole", iam_client.get_role, RoleName=role_name)
    role = response.get("Role")
    if not isinstance(role, dict):
        raise PriorWorkerRoleAPIError("GetRole returned a malformed role.")
    return cast(dict[str, object], role)


def _get_exact_role(
    iam_client: Any, *, role_name: str, role_arn: str
) -> dict[str, object]:
    role = _get_role(iam_client, role_name=role_name)
    if role.get("RoleName") != role_name or role.get("Arn") != role_arn:
        raise PriorWorkerRoleError("AWS IAM returned a role other than the exact requested ARN.")
    return role


def _max_session_duration(role: Mapping[str, object]) -> int:
    value = role.get("MaxSessionDuration")
    if type(value) is not int or not 900 <= value <= 43200:
        raise PriorWorkerRoleAPIError("GetRole returned an invalid maximum session duration.")
    return value


def _validate_release_binding(
    *,
    role_arn: str,
    prior_release_revision: str,
    prior_deployment_id: str,
    current_release_revision: str,
    current_deployment_id: str,
) -> str:
    for label, revision in (
        ("Prior", prior_release_revision),
        ("Current", current_release_revision),
    ):
        if _REVISION_PATTERN.fullmatch(revision) is None or revision == "0" * 40:
            raise PriorWorkerRoleError(f"{label} release revision must be an exact Git SHA.")
    for label, deployment_id in (
        ("Prior", prior_deployment_id),
        ("Current", current_deployment_id),
    ):
        if _DEPLOYMENT_PATTERN.fullmatch(deployment_id) is None:
            raise PriorWorkerRoleError(f"{label} deployment ID is not a bounded identifier.")
    if (
        prior_release_revision == current_release_revision
        and prior_deployment_id == current_deployment_id
    ):
        raise PriorWorkerRoleError("Prior and current release identities must be distinct.")
    role_match = _ROLE_ARN_PATTERN.fullmatch(role_arn)
    if role_match is None or "*" in role_arn:
        raise PriorWorkerRoleError("Prior worker role ARN must be one exact IAM role ARN.")
    role_path = role_match.group(3)
    role_name = role_path.rsplit("/", maxsplit=1)[-1]
    suffix = hashlib.sha256(
        f"{prior_deployment_id}:{prior_release_revision}".encode()
    ).hexdigest()[:12]
    if not role_name.endswith(f"-worker-{suffix}-task"):
        raise PriorWorkerRoleError(
            "Prior worker role ARN is not bound to the supplied release identity."
        )
    return role_name


def _quarantine_policy(cutoff: datetime) -> dict[str, object]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "RevokeOlderSessions",
                "Effect": "Deny",
                "Action": "*",
                "Resource": "*",
                "Condition": {
                    "DateLessThan": {"aws:TokenIssueTime": _format_time(cutoff)}
                },
            }
        ],
    }


def _quarantine_policy_cutoff(policy: Mapping[str, object]) -> datetime:
    statements = policy.get("Statement")
    if not isinstance(statements, list) or len(statements) != 1:
        raise PriorWorkerRoleError("Live quarantine policy is not an exact cutoff deny.")
    statement = statements[0]
    condition = statement.get("Condition") if isinstance(statement, dict) else None
    less_than = condition.get("DateLessThan") if isinstance(condition, dict) else None
    cutoff_value = less_than.get("aws:TokenIssueTime") if isinstance(less_than, dict) else None
    cutoff = _parse_time(cutoff_value, "Live quarantine cutoff")
    if policy != _quarantine_policy(cutoff):
        raise PriorWorkerRoleError("Live quarantine policy is not an exact cutoff deny.")
    return cutoff


def _decode_policy_document(value: object, label: str) -> dict[str, object]:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    if not isinstance(value, str) or not value or len(value) > 16384:
        raise PriorWorkerRoleAPIError(f"{label} is missing or malformed.")
    try:
        decoded = json.loads(unquote(value), object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, PriorWorkerRoleAPIError) as error:
        raise PriorWorkerRoleAPIError(f"{label} is not unambiguous JSON.") from error
    if not isinstance(decoded, dict):
        raise PriorWorkerRoleAPIError(f"{label} is not a JSON object.")
    return cast(dict[str, object], decoded)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PriorWorkerRoleAPIError("IAM policy JSON contains duplicate keys.")
        result[key] = value
    return result


def _policy_digest(policy: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(policy).encode()).hexdigest()


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _propagation_deadline(observation: Mapping[str, object]) -> datetime:
    cutoff = _parse_time(observation.get("revocation_cutoff_at"), "Signed revocation cutoff")
    propagation = observation.get("propagation_wait_seconds")
    if type(propagation) is not int:
        raise PriorWorkerRoleError("Signed IAM propagation wait is malformed.")
    return cutoff + timedelta(seconds=propagation)


def _decision_time(value: datetime | None) -> datetime:
    return _require_utc_datetime(value or datetime.now(UTC), "Decision time").replace(
        microsecond=0
    )


def _require_utc_datetime(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PriorWorkerRoleError(f"{label} must include a timezone.")
    return value.astimezone(UTC)


def _parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not 20 <= len(value) <= 40:
        raise PriorWorkerRoleError(f"{label} is not a bounded timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PriorWorkerRoleError(f"{label} is not ISO-8601.") from error
    return _require_utc_datetime(parsed, label)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _target_arguments(args: argparse.Namespace) -> dict[str, str]:
    return {
        "db_user_arn": args.expected_db_user_arn,
        "s3_object_prefix_arn": args.expected_s3_object_prefix_arn,
        "kms_key_arn": args.expected_kms_key_arn,
        "bedrock_model_arn": args.expected_bedrock_model_arn,
    }


def _add_release_binding_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--prior-release-revision", required=True)
    parser.add_argument("--prior-deployment-id", required=True)
    parser.add_argument("--current-release-revision", required=True)
    parser.add_argument("--current-deployment-id", required=True)


def _add_authenticated_evidence_arguments(
    parser: argparse.ArgumentParser, *, require_recent_probe: bool
) -> None:
    parser.add_argument("--evidence-record", required=True, type=Path)
    parser.add_argument("--evidence-issuer-role-arn", required=True)
    parser.add_argument("--evidence-signing-key-arn", required=True)
    parser.add_argument("--expected-db-user-arn", required=True)
    parser.add_argument("--expected-s3-object-prefix-arn", required=True)
    parser.add_argument("--expected-kms-key-arn", required=True)
    parser.add_argument("--expected-bedrock-model-arn", required=True)
    parser.add_argument("--maximum-evidence-age-days", type=int, default=30)
    if require_recent_probe:
        parser.add_argument(
            "--maximum-probe-age-seconds",
            type=int,
            default=DEFAULT_MAXIMUM_PROBE_AGE_SECONDS,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed quarantine and cleanup for a superseded AI-FDE worker role."
    )
    parser.add_argument("--region", required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    quarantine = actions.add_parser("quarantine")
    _add_release_binding_arguments(quarantine)
    quarantine.add_argument("--captured-session-issued-at", required=True)
    quarantine.add_argument("--captured-session-expires-at", required=True)
    quarantine.add_argument(
        "--propagation-wait-seconds",
        type=int,
        default=DEFAULT_PROPAGATION_WAIT_SECONDS,
    )
    state_rm = actions.add_parser("verify-state-rm")
    _add_release_binding_arguments(state_rm)
    _add_authenticated_evidence_arguments(state_rm, require_recent_probe=True)
    cleanup = actions.add_parser("cleanup")
    _add_release_binding_arguments(cleanup)
    _add_authenticated_evidence_arguments(cleanup, require_recent_probe=False)
    return parser


def _cli_error(parser: argparse.ArgumentParser, error: Exception) -> NoReturn:
    parser.exit(2, f"error: {error}\n")


def main() -> None:
    import boto3

    parser = _parser()
    args = parser.parse_args()
    session = boto3.Session(region_name=args.region)
    iam_client = session.client("iam")
    try:
        if args.action == "quarantine":
            result = quarantine_prior_worker_role(
                iam_client,
                role_arn=args.role_arn,
                prior_release_revision=args.prior_release_revision,
                prior_deployment_id=args.prior_deployment_id,
                current_release_revision=args.current_release_revision,
                current_deployment_id=args.current_deployment_id,
                captured_session_issued_at=_parse_time(
                    args.captured_session_issued_at,
                    "Captured prior-worker session issuance",
                ),
                captured_session_expires_at=_parse_time(
                    args.captured_session_expires_at,
                    "Captured prior-worker session expiry",
                ),
                propagation_wait_seconds=args.propagation_wait_seconds,
            )
        else:
            operation = (
                verify_prior_worker_state_rm
                if args.action == "verify-state-rm"
                else cleanup_prior_worker_role
            )
            result = operation(
                iam_client,
                session.client("kms"),
                evidence_record=args.evidence_record,
                role_arn=args.role_arn,
                prior_release_revision=args.prior_release_revision,
                prior_deployment_id=args.prior_deployment_id,
                current_release_revision=args.current_release_revision,
                current_deployment_id=args.current_deployment_id,
                evidence_issuer_role_arn=args.evidence_issuer_role_arn,
                evidence_signing_key_arn=args.evidence_signing_key_arn,
                expected_targets=_target_arguments(args),
                maximum_evidence_age_days=args.maximum_evidence_age_days,
                **(
                    {"maximum_probe_age_seconds": args.maximum_probe_age_seconds}
                    if args.action == "verify-state-rm"
                    else {}
                ),
            )
    except (PriorWorkerRoleError, EvidenceRecordError) as error:
        _cli_error(parser, error)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
