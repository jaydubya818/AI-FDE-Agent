from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

import pytest
from botocore.exceptions import ClientError

from scripts.qualification_evidence import EvidenceRecordError, build_signed_evidence_record
from scripts.quarantine_prior_worker_role import (
    PriorWorkerRoleAccessDeniedError,
    PriorWorkerRoleAPIError,
    PriorWorkerRoleError,
    PriorWorkerRoleNotFoundError,
    cleanup_prior_worker_role,
    quarantine_prior_worker_role,
    verify_prior_worker_state_rm,
)

PRIOR_REVISION = "9" * 40
PRIOR_DEPLOYMENT_ID = "prior-deployment-2026"
CURRENT_REVISION = "a" * 40
CURRENT_DEPLOYMENT_ID = "current-deployment-2026"
ROLE_SUFFIX = hashlib.sha256(
    f"{PRIOR_DEPLOYMENT_ID}:{PRIOR_REVISION}".encode()
).hexdigest()[:12]
ROLE_NAME = f"ai-fde-production-worker-{ROLE_SUFFIX}-task"
ROLE_ARN = f"arn:aws:iam::123456789012:role/{ROLE_NAME}"
NOW = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
ISSUER_ROLE_ARN = "arn:aws:iam::123456789012:role/ai-fde-evidence-issuer"
SIGNING_KEY_ARN = (
    "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
)
TARGETS = {
    "db_user_arn": (
        "arn:aws:rds-db:us-east-1:123456789012:"
        "dbuser:db-ABCDEFGHIJKLMNOPQRSTUVWXY/ai_fde_worker_0123456789ab"
    ),
    "s3_object_prefix_arn": (
        "arn:aws:s3:::ai-fde-evidence/engagements/"
        "70000000-0000-4000-8000-000000000003/*"
    ),
    "kms_key_arn": SIGNING_KEY_ARN,
    "bedrock_model_arn": (
        "arn:aws:bedrock:us-east-1::foundation-model/profile-v1"
    ),
}
DISABLED_TRUST_POLICY = {
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


class CommonArguments(TypedDict):
    evidence_record: Path
    role_arn: str
    prior_release_revision: str
    prior_deployment_id: str
    current_release_revision: str
    current_deployment_id: str
    evidence_issuer_role_arn: str
    evidence_signing_key_arn: str
    expected_targets: dict[str, str]


class FakeKMS:
    def sign(self, **request: Any) -> dict[str, object]:
        return {
            "KeyId": request["KeyId"],
            "Signature": b"offline-kms-signature:" + request["Message"],
        }

    def verify(self, **request: Any) -> dict[str, object]:
        expected = b"offline-kms-signature:" + request["Message"]
        return {
            "KeyId": request["KeyId"],
            "SignatureValid": request["Signature"] == expected,
        }


class RejectingKMS(FakeKMS):
    def verify(self, **request: Any) -> dict[str, object]:
        return {"KeyId": request["KeyId"], "SignatureValid": False}


class FakeIAM:
    def __init__(self) -> None:
        self.exists = True
        self.role: dict[str, object] = {
            "RoleName": ROLE_NAME,
            "Arn": ROLE_ARN,
            "MaxSessionDuration": 3600,
            "AssumeRolePolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            },
            "PermissionsBoundary": {
                "PermissionsBoundaryArn": (
                    "arn:aws:iam::123456789012:policy/worker-boundary"
                )
            },
        }
        self.inline_policies: dict[str, dict[str, object]] = {
            "deployment-worker-database-connect": {
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Action": "rds-db:connect"}],
            }
        }
        self.attached_policies = [
            {
                "PolicyName": "worker-managed",
                "PolicyArn": "arn:aws:iam::123456789012:policy/worker-managed",
            }
        ]
        self.instance_profiles = [
            {
                "InstanceProfileName": "worker-profile",
                "Arn": "arn:aws:iam::123456789012:instance-profile/worker-profile",
            }
        ]
        self.errors: dict[str, str] = {}
        self.calls: list[str] = []

    def _before(self, operation: str) -> None:
        self.calls.append(operation)
        code = self.errors.get(operation)
        if code is not None:
            raise ClientError(
                {"Error": {"Code": code, "Message": "intentionally not surfaced"}},
                operation,
            )

    def _require_role(self, operation: str) -> None:
        self._before(operation)
        if not self.exists:
            raise ClientError(
                {"Error": {"Code": "NoSuchEntity", "Message": "test"}}, operation
            )

    def get_role(self, *, RoleName: str) -> dict[str, object]:
        self._require_role("GetRole")
        assert RoleName == ROLE_NAME
        return {"Role": deepcopy(self.role)}

    def put_role_policy(
        self, *, RoleName: str, PolicyName: str, PolicyDocument: str
    ) -> dict[str, object]:
        self._require_role("PutRolePolicy")
        assert RoleName == ROLE_NAME
        self.inline_policies[PolicyName] = json.loads(PolicyDocument)
        return {}

    def update_assume_role_policy(
        self, *, RoleName: str, PolicyDocument: str
    ) -> dict[str, object]:
        self._require_role("UpdateAssumeRolePolicy")
        assert RoleName == ROLE_NAME
        self.role["AssumeRolePolicyDocument"] = json.loads(PolicyDocument)
        return {}

    def list_attached_role_policies(
        self, *, RoleName: str, Marker: str | None = None
    ) -> dict[str, object]:
        self._require_role("ListAttachedRolePolicies")
        assert RoleName == ROLE_NAME and Marker is None
        return {"AttachedPolicies": deepcopy(self.attached_policies), "IsTruncated": False}

    def detach_role_policy(self, *, RoleName: str, PolicyArn: str) -> dict[str, object]:
        self._require_role("DetachRolePolicy")
        assert RoleName == ROLE_NAME
        self.attached_policies = [
            policy for policy in self.attached_policies if policy["PolicyArn"] != PolicyArn
        ]
        return {}

    def list_role_policies(
        self, *, RoleName: str, Marker: str | None = None
    ) -> dict[str, object]:
        self._require_role("ListRolePolicies")
        assert RoleName == ROLE_NAME and Marker is None
        return {"PolicyNames": list(self.inline_policies), "IsTruncated": False}

    def delete_role_policy(
        self, *, RoleName: str, PolicyName: str
    ) -> dict[str, object]:
        self._require_role("DeleteRolePolicy")
        assert RoleName == ROLE_NAME
        if PolicyName not in self.inline_policies:
            raise ClientError(
                {"Error": {"Code": "NoSuchEntity", "Message": "test"}},
                "DeleteRolePolicy",
            )
        del self.inline_policies[PolicyName]
        return {}

    def delete_role_permissions_boundary(self, *, RoleName: str) -> dict[str, object]:
        self._require_role("DeleteRolePermissionsBoundary")
        assert RoleName == ROLE_NAME
        self.role.pop("PermissionsBoundary", None)
        return {}

    def list_instance_profiles_for_role(
        self, *, RoleName: str, Marker: str | None = None
    ) -> dict[str, object]:
        self._require_role("ListInstanceProfilesForRole")
        assert RoleName == ROLE_NAME and Marker is None
        return {"InstanceProfiles": deepcopy(self.instance_profiles), "IsTruncated": False}

    def remove_role_from_instance_profile(
        self, *, InstanceProfileName: str, RoleName: str
    ) -> dict[str, object]:
        self._require_role("RemoveRoleFromInstanceProfile")
        assert RoleName == ROLE_NAME
        self.instance_profiles = [
            profile
            for profile in self.instance_profiles
            if profile["InstanceProfileName"] != InstanceProfileName
        ]
        return {}

    def get_role_policy(self, *, RoleName: str, PolicyName: str) -> dict[str, object]:
        self._require_role("GetRolePolicy")
        assert RoleName == ROLE_NAME
        if PolicyName not in self.inline_policies:
            raise ClientError(
                {"Error": {"Code": "NoSuchEntity", "Message": "test"}},
                "GetRolePolicy",
            )
        return {"PolicyDocument": deepcopy(self.inline_policies[PolicyName])}

    def delete_role(self, *, RoleName: str) -> dict[str, object]:
        self._require_role("DeleteRole")
        assert RoleName == ROLE_NAME
        if self.inline_policies or self.attached_policies or self.instance_profiles:
            raise ClientError(
                {"Error": {"Code": "DeleteConflict", "Message": "test"}},
                "DeleteRole",
            )
        self.exists = False
        return {}


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _policy(cutoff: datetime) -> dict[str, object]:
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


def _digest(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _quarantined_iam(cutoff: datetime) -> FakeIAM:
    iam = FakeIAM()
    iam.role["AssumeRolePolicyDocument"] = deepcopy(DISABLED_TRUST_POLICY)
    iam.role.pop("PermissionsBoundary")
    iam.inline_policies = {"AWSRevokeOlderSessions": _policy(cutoff)}
    iam.attached_policies = []
    iam.instance_profiles = []
    return iam


def _write_evidence(
    path: Path,
    *,
    cutoff: datetime,
    completed_at: datetime,
    probe_completed_at: datetime,
    identity_state: str = "retained-quarantined",
    deleted_at: datetime | None = None,
    captured_session_issued_at: datetime | None = None,
    captured_session_expires_at: datetime | None = None,
) -> None:
    session_issued_at = captured_session_issued_at or cutoff - timedelta(minutes=1)
    session_expires_at = captured_session_expires_at or (
        session_issued_at + timedelta(seconds=3600)
    )
    observation = {
        "role_arn": ROLE_ARN,
        "prior_release_revision": PRIOR_REVISION,
        "prior_deployment_id": PRIOR_DEPLOYMENT_ID,
        "identity_state": identity_state,
        "quarantine_control": "inline-deny-pre-cutoff-sessions",
        "quarantine_policy_digest": _digest(_policy(cutoff)),
        "assume_role_disabled": True,
        "permission_grants_stripped": True,
        "quarantine_applied_at": _format_time(cutoff),
        "revocation_cutoff_at": _format_time(cutoff),
        "session_expiry_not_before": _format_time(cutoff + timedelta(seconds=3660)),
        "max_session_duration_seconds": 3600,
        "propagation_wait_seconds": 60,
        "captured_session_issued_at": _format_time(session_issued_at),
        "captured_session_expires_at": _format_time(session_expires_at),
        "live_probe_completed_at": _format_time(probe_completed_at),
        "deleted_at": _format_time(deleted_at) if deleted_at is not None else None,
        "targets": TARGETS,
        "probe_results": {
            "rds_db_connect": "denied",
            "s3_get_current_prefix": "denied",
            "s3_put_current_prefix": "denied",
            "kms_decrypt_current_key": "denied",
            "kms_generate_data_key_current_key": "denied",
            "bedrock_invoke_current_model": "denied",
        },
    }
    record = build_signed_evidence_record(
        record_id="prior-worker-revocation-evidence",
        evidence_type="prior-worker-session-revocation",
        release_revision=CURRENT_REVISION,
        deployment_id=CURRENT_DEPLOYMENT_ID,
        completed_at=completed_at,
        results={"roles": [observation]},
        issuer_role_arn=ISSUER_ROLE_ARN,
        signing_key_arn=SIGNING_KEY_ARN,
        caller_principal_arn=(
            "arn:aws:sts::123456789012:"
            "assumed-role/ai-fde-evidence-issuer/release-session"
        ),
        kms_client=FakeKMS(),
    )
    path.write_text(json.dumps(record), encoding="utf-8")


def _common_arguments(path: Path) -> CommonArguments:
    return {
        "evidence_record": path,
        "role_arn": ROLE_ARN,
        "prior_release_revision": PRIOR_REVISION,
        "prior_deployment_id": PRIOR_DEPLOYMENT_ID,
        "current_release_revision": CURRENT_REVISION,
        "current_deployment_id": CURRENT_DEPLOYMENT_ID,
        "evidence_issuer_role_arn": ISSUER_ROLE_ARN,
        "evidence_signing_key_arn": SIGNING_KEY_ARN,
        "expected_targets": TARGETS,
    }


def test_quarantine_strips_every_grant_and_emits_exact_boundaries() -> None:
    iam = FakeIAM()

    receipt = quarantine_prior_worker_role(
        iam,
        role_arn=ROLE_ARN,
        prior_release_revision=PRIOR_REVISION,
        prior_deployment_id=PRIOR_DEPLOYMENT_ID,
        current_release_revision=CURRENT_REVISION,
        current_deployment_id=CURRENT_DEPLOYMENT_ID,
        captured_session_issued_at=NOW - timedelta(minutes=1),
        captured_session_expires_at=NOW + timedelta(minutes=59),
        propagation_wait_seconds=60,
        now=NOW,
    )

    assert iam.role["AssumeRolePolicyDocument"] == DISABLED_TRUST_POLICY
    assert iam.role.get("PermissionsBoundary") is None
    assert iam.attached_policies == []
    assert iam.instance_profiles == []
    assert list(iam.inline_policies) == ["AWSRevokeOlderSessions"]
    assert iam.inline_policies["AWSRevokeOlderSessions"] == _policy(NOW)
    assert receipt["propagation_deadline_at"] == _format_time(NOW + timedelta(seconds=60))
    assert receipt["session_expiry_not_before"] == _format_time(
        NOW + timedelta(seconds=3660)
    )
    assert receipt["stripped_grant_counts"] == {
        "attached_managed_policies": 1,
        "inline_policies": 1,
        "permissions_boundaries": 1,
        "instance_profile_bindings": 1,
    }
    serialized = json.dumps(receipt)
    assert "rds-db:connect" not in serialized
    assert "worker-managed" not in serialized

    repeated = quarantine_prior_worker_role(
        iam,
        role_arn=ROLE_ARN,
        prior_release_revision=PRIOR_REVISION,
        prior_deployment_id=PRIOR_DEPLOYMENT_ID,
        current_release_revision=CURRENT_REVISION,
        current_deployment_id=CURRENT_DEPLOYMENT_ID,
        captured_session_issued_at=NOW - timedelta(minutes=1),
        captured_session_expires_at=NOW + timedelta(minutes=59),
        propagation_wait_seconds=60,
        now=NOW,
    )
    assert repeated["status"] == "quarantined"
    assert repeated["stripped_grant_counts"] == {
        "attached_managed_policies": 0,
        "inline_policies": 0,
        "permissions_boundaries": 0,
        "instance_profile_bindings": 0,
    }


def test_quarantine_rejects_role_not_bound_to_prior_release_before_aws() -> None:
    iam = FakeIAM()
    with pytest.raises(PriorWorkerRoleError, match="not bound"):
        quarantine_prior_worker_role(
            iam,
            role_arn=ROLE_ARN.replace(ROLE_SUFFIX, "0" * 12),
            prior_release_revision=PRIOR_REVISION,
            prior_deployment_id=PRIOR_DEPLOYMENT_ID,
            current_release_revision=CURRENT_REVISION,
            current_deployment_id=CURRENT_DEPLOYMENT_ID,
            captured_session_issued_at=NOW,
            captured_session_expires_at=NOW + timedelta(minutes=59),
            now=NOW,
        )
    assert iam.calls == []


def test_quarantine_rejects_session_issued_at_exact_cutoff() -> None:
    iam = FakeIAM()
    with pytest.raises(PriorWorkerRoleError, match="must be earlier"):
        quarantine_prior_worker_role(
            iam,
            role_arn=ROLE_ARN,
            prior_release_revision=PRIOR_REVISION,
            prior_deployment_id=PRIOR_DEPLOYMENT_ID,
            current_release_revision=CURRENT_REVISION,
            current_deployment_id=CURRENT_DEPLOYMENT_ID,
            captured_session_issued_at=NOW,
            captured_session_expires_at=NOW + timedelta(minutes=59),
            now=NOW,
        )
    assert iam.calls == []


@pytest.mark.parametrize(
    "captured_expiry",
    [NOW + timedelta(seconds=60), NOW + timedelta(seconds=3600)],
)
def test_quarantine_rejects_unprobeable_or_overlong_session_expiry(
    captured_expiry: datetime,
) -> None:
    iam = FakeIAM()
    with pytest.raises(PriorWorkerRoleError, match="remain live|exceeds"):
        quarantine_prior_worker_role(
            iam,
            role_arn=ROLE_ARN,
            prior_release_revision=PRIOR_REVISION,
            prior_deployment_id=PRIOR_DEPLOYMENT_ID,
            current_release_revision=CURRENT_REVISION,
            current_deployment_id=CURRENT_DEPLOYMENT_ID,
            captured_session_issued_at=NOW - timedelta(seconds=1),
            captured_session_expires_at=captured_expiry,
            propagation_wait_seconds=60,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("error_code", "error_type"),
    [
        ("NoSuchEntity", PriorWorkerRoleNotFoundError),
        ("AccessDenied", PriorWorkerRoleAccessDeniedError),
        ("Throttling", PriorWorkerRoleAPIError),
    ],
)
def test_quarantine_distinguishes_iam_errors(
    error_code: str, error_type: type[PriorWorkerRoleError]
) -> None:
    iam = FakeIAM()
    iam.errors["GetRole"] = error_code
    with pytest.raises(error_type):
        quarantine_prior_worker_role(
            iam,
            role_arn=ROLE_ARN,
            prior_release_revision=PRIOR_REVISION,
            prior_deployment_id=PRIOR_DEPLOYMENT_ID,
            current_release_revision=CURRENT_REVISION,
            current_deployment_id=CURRENT_DEPLOYMENT_ID,
            captured_session_issued_at=NOW - timedelta(seconds=1),
            captured_session_expires_at=NOW + timedelta(minutes=59),
            now=NOW,
        )


def test_state_rm_authorization_requires_signed_current_probes_and_never_mutates(
    tmp_path: Path,
) -> None:
    cutoff = NOW - timedelta(seconds=60)
    iam = _quarantined_iam(cutoff)
    evidence = tmp_path / "revocation.json"
    _write_evidence(
        evidence,
        cutoff=cutoff,
        completed_at=NOW,
        probe_completed_at=NOW,
    )
    iam.calls.clear()

    receipt = verify_prior_worker_state_rm(
        iam,
        FakeKMS(),
        **_common_arguments(evidence),
        maximum_probe_age_seconds=60,
        now=NOW,
    )

    assert receipt["authorized"] is True
    assert receipt["propagation_deadline_at"] == _format_time(NOW)
    assert all(
        not call.startswith(("Put", "Update", "Detach", "Delete", "Remove"))
        for call in iam.calls
    )


def test_state_rm_rejects_wrong_target_before_reading_iam(tmp_path: Path) -> None:
    cutoff = NOW - timedelta(seconds=60)
    iam = _quarantined_iam(cutoff)
    evidence = tmp_path / "revocation.json"
    _write_evidence(
        evidence,
        cutoff=cutoff,
        completed_at=NOW,
        probe_completed_at=NOW,
    )
    wrong_targets = {**TARGETS, "bedrock_model_arn": TARGETS["bedrock_model_arn"] + "-wrong"}
    wrong_arguments = _common_arguments(evidence)
    wrong_arguments["expected_targets"] = wrong_targets

    with pytest.raises(PriorWorkerRoleError, match="exact current targets"):
        verify_prior_worker_state_rm(
            iam,
            FakeKMS(),
            **wrong_arguments,
            now=NOW,
        )
    assert iam.calls == []


def test_cleanup_refuses_one_second_before_ttl_and_succeeds_at_exact_boundary(
    tmp_path: Path,
) -> None:
    cutoff = NOW - timedelta(seconds=3660)
    expiry = NOW
    probe_at = cutoff + timedelta(seconds=120)
    iam = _quarantined_iam(cutoff)
    evidence = tmp_path / "revocation.json"
    _write_evidence(
        evidence,
        cutoff=cutoff,
        completed_at=expiry - timedelta(seconds=1),
        probe_completed_at=probe_at,
    )

    with pytest.raises(PriorWorkerRoleError, match="forbidden before session TTL"):
        cleanup_prior_worker_role(
            iam,
            FakeKMS(),
            **_common_arguments(evidence),
            now=expiry - timedelta(seconds=1),
        )
    assert "DeleteRole" not in iam.calls

    receipt = cleanup_prior_worker_role(
        iam,
        FakeKMS(),
        **_common_arguments(evidence),
        now=expiry,
    )
    assert receipt["status"] == "deleted"
    assert iam.exists is False
    observations = receipt["sealable_observations"]
    assert isinstance(observations, dict)
    role = observations["roles"][0]
    assert role["identity_state"] == "deleted-after-ttl"
    assert role["deleted_at"] == _format_time(expiry)


def test_cleanup_is_idempotent_after_authorized_role_disappearance(tmp_path: Path) -> None:
    cutoff = NOW - timedelta(seconds=3660)
    evidence = tmp_path / "revocation.json"
    _write_evidence(
        evidence,
        cutoff=cutoff,
        completed_at=NOW,
        probe_completed_at=cutoff + timedelta(seconds=120),
    )
    iam = _quarantined_iam(cutoff)
    iam.exists = False

    receipt = cleanup_prior_worker_role(
        iam,
        FakeKMS(),
        **_common_arguments(evidence),
        now=NOW,
    )
    assert receipt["status"] == "already-deleted"
    assert "DeleteRole" not in iam.calls


def test_state_rm_rejects_stale_probes_and_cleanup_preserves_access_denial(
    tmp_path: Path,
) -> None:
    cutoff = NOW - timedelta(seconds=3660)
    evidence = tmp_path / "revocation.json"
    _write_evidence(
        evidence,
        cutoff=cutoff,
        completed_at=NOW - timedelta(minutes=5),
        probe_completed_at=cutoff + timedelta(seconds=120),
    )
    iam = _quarantined_iam(cutoff)
    with pytest.raises(PriorWorkerRoleError, match="no longer current"):
        verify_prior_worker_state_rm(
            iam,
            FakeKMS(),
            **_common_arguments(evidence),
            maximum_probe_age_seconds=60,
            now=NOW,
        )
    assert iam.calls == []

    fresh = tmp_path / "fresh-revocation.json"
    _write_evidence(
        fresh,
        cutoff=cutoff,
        completed_at=NOW,
        probe_completed_at=cutoff + timedelta(seconds=120),
    )
    iam.errors["GetRole"] = "AccessDenied"
    with pytest.raises(PriorWorkerRoleAccessDeniedError):
        cleanup_prior_worker_role(
            iam,
            FakeKMS(),
            **_common_arguments(fresh),
            now=NOW,
        )


def test_cleanup_rejects_policy_cutoff_not_bound_to_signed_evidence(
    tmp_path: Path,
) -> None:
    cutoff = NOW - timedelta(seconds=3660)
    iam = _quarantined_iam(cutoff + timedelta(seconds=1))
    evidence = tmp_path / "revocation.json"
    _write_evidence(
        evidence,
        cutoff=cutoff,
        completed_at=NOW,
        probe_completed_at=cutoff + timedelta(seconds=120),
    )

    with pytest.raises(PriorWorkerRoleError, match="differs from signed evidence"):
        cleanup_prior_worker_role(
            iam,
            FakeKMS(),
            **_common_arguments(evidence),
            now=NOW,
        )
    assert iam.exists is True


def test_cleanup_requires_kms_authenticated_evidence_before_iam(tmp_path: Path) -> None:
    cutoff = NOW - timedelta(seconds=3660)
    iam = _quarantined_iam(cutoff)
    evidence = tmp_path / "revocation.json"
    _write_evidence(
        evidence,
        cutoff=cutoff,
        completed_at=NOW,
        probe_completed_at=cutoff + timedelta(seconds=120),
    )

    with pytest.raises(EvidenceRecordError, match="signature is invalid"):
        cleanup_prior_worker_role(
            iam,
            RejectingKMS(),
            **_common_arguments(evidence),
            now=NOW,
        )
    assert iam.calls == []


def test_cleanup_requires_live_policy_and_restores_it_if_delete_fails(
    tmp_path: Path,
) -> None:
    cutoff = NOW - timedelta(seconds=3660)
    evidence = tmp_path / "revocation.json"
    _write_evidence(
        evidence,
        cutoff=cutoff,
        completed_at=NOW,
        probe_completed_at=cutoff + timedelta(seconds=120),
    )
    missing_policy = _quarantined_iam(cutoff)
    missing_policy.inline_policies = {}
    with pytest.raises(PriorWorkerRoleError, match="unexpected inline"):
        cleanup_prior_worker_role(
            missing_policy,
            FakeKMS(),
            **_common_arguments(evidence),
            now=NOW,
        )
    assert "DeleteRole" not in missing_policy.calls

    denied = _quarantined_iam(cutoff)
    denied.errors["DeleteRole"] = "AccessDenied"
    with pytest.raises(PriorWorkerRoleAccessDeniedError):
        cleanup_prior_worker_role(
            denied,
            FakeKMS(),
            **_common_arguments(evidence),
            now=NOW,
        )
    assert denied.inline_policies == {"AWSRevokeOlderSessions": _policy(cutoff)}


def test_signed_probe_at_captured_session_expiry_cannot_authorize_cleanup(
    tmp_path: Path,
) -> None:
    cutoff = NOW - timedelta(seconds=3660)
    captured_expiry = cutoff + timedelta(minutes=30)
    with pytest.raises(EvidenceRecordError, match="session revocation timing"):
        _write_evidence(
            tmp_path / "invalid-revocation.json",
            cutoff=cutoff,
            completed_at=NOW,
            probe_completed_at=captured_expiry,
            captured_session_expires_at=captured_expiry,
        )
