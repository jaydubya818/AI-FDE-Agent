from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ai_fde.modules.identity.database import worker_database_user_for_release
from scripts.qualification_evidence import (
    EVIDENCE_SCHEMA_VERSION,
    EvidenceRecordError,
    _derive_results_from_observations,
    _reject_generic_result_claims,
    build_signed_evidence_record,
    build_synthetic_evidence_record,
    canonical_record_digest,
    load_and_validate_evidence_record,
)

REVISION = "a" * 40
DEPLOYMENT_ID = "deploy-2026-09-04-a"
NOW = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
ISSUER_ROLE_ARN = "arn:aws:iam::123456789012:role/ai-fde-evidence-issuer"
ISSUER_PRINCIPAL_ARN = (
    "arn:aws:sts::123456789012:assumed-role/ai-fde-evidence-issuer/release-42"
)
SIGNING_KEY_ARN = (
    "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
)


class FakeKMS:
    def sign(self, **request: Any) -> dict[str, object]:
        return {
            "KeyId": request["KeyId"],
            "Signature": b"offline-kms-pss-signature:" + request["Message"],
        }

    def verify(self, **request: Any) -> dict[str, object]:
        expected = b"offline-kms-pss-signature:" + request["Message"]
        return {
            "KeyId": request["KeyId"],
            "SignatureValid": request["Signature"] == expected,
        }


def _results() -> dict[str, object]:
    return {
        "source_identifier": "ai-fde-design-partner",
        "target_identifier": "ai-fde-restore-20260904",
        "database_role": "ai_fde_app",
        "audit_event_id": "70000000-0000-4000-8000-000000000001",
        "audit_fingerprint": "sha256:" + "b" * 64,
        "digest_subject_type": "deployment-package",
        "digest_subject_id": "70000000-0000-4000-8000-000000000002",
        "stored_digest": "sha256:" + "c" * 64,
        "row_fingerprint": "sha256:" + "d" * 64,
        "source_target_isolated": True,
        "durable_record_matched": True,
        "digest_matched": True,
    }


def _prior_worker_role_observation(
    *,
    identity_state: str = "retained-quarantined",
    deleted_at: str | None = None,
) -> dict[str, object]:
    cutoff = NOW - timedelta(hours=2)
    session_expiry = cutoff + timedelta(seconds=3660)
    return {
        "role_arn": "arn:aws:iam::123456789012:role/ai-fde-worker-prior",
        "prior_release_revision": "9" * 40,
        "prior_deployment_id": "deploy-2026-08-01-a",
        "identity_state": identity_state,
        "quarantine_control": "inline-deny-pre-cutoff-sessions",
        "quarantine_policy_digest": "sha256:" + "7" * 64,
        "assume_role_disabled": True,
        "permission_grants_stripped": True,
        "quarantine_applied_at": cutoff.isoformat(),
        "revocation_cutoff_at": cutoff.isoformat(),
        "session_expiry_not_before": session_expiry.isoformat(),
        "max_session_duration_seconds": 3600,
        "propagation_wait_seconds": 60,
        "captured_session_issued_at": (cutoff - timedelta(minutes=1)).isoformat(),
        "captured_session_expires_at": (cutoff + timedelta(minutes=59)).isoformat(),
        "live_probe_completed_at": (cutoff + timedelta(seconds=60)).isoformat(),
        "deleted_at": deleted_at,
        "targets": {
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
                "arn:aws:bedrock:us-east-1::"
                "foundation-model/anthropic.claude-3-haiku-20240307-v1:0"
            ),
        },
        "probe_results": {
            "rds_db_connect": "denied",
            "s3_get_current_prefix": "denied",
            "s3_put_current_prefix": "denied",
            "kms_decrypt_current_key": "denied",
            "kms_generate_data_key_current_key": "denied",
            "bedrock_invoke_current_model": "denied",
        },
    }


@pytest.mark.parametrize(
    ("evidence_type", "results"),
    [
        (
            "auth0-live-validation",
            {
                "issuer_url": "https://tenant.us.auth0.com/",
                "callback_url": "https://ai-fde.example/api/auth/callback",
                "authorization_request_id": "70000000-0000-4000-8000-000000000010",
                "authorization_code_challenge_method": "S256",
                "authorization_response_type": "code",
                "allowlisted_callback_request_id": (
                    "70000000-0000-4000-8000-000000000011"
                ),
                "allowlisted_callback_status_code": 303,
                "unallowlisted_callback_request_id": (
                    "70000000-0000-4000-8000-000000000012"
                ),
                "unallowlisted_callback_status_code": 403,
                "logout_request_id": "70000000-0000-4000-8000-000000000013",
                "logout_status_code": 204,
                "revoked_session_request_id": (
                    "70000000-0000-4000-8000-000000000014"
                ),
                "revoked_session_status_code": 401,
            },
        ),
        ("isolated-restore-rehearsal", _results()),
        (
            "deletion-boundary-rehearsal",
            {
                "engagement_id": "70000000-0000-4000-8000-000000000003",
                "deletion_receipt_id": "70000000-0000-4000-8000-000000000004",
                "application_rows_remaining": 0,
                "current_objects_remaining": 0,
                "object_versions_deleted": 2,
                "delete_markers_deleted": 1,
                "object_versions_remaining": 0,
                "delete_markers_remaining": 0,
                "control_engagement_id": "70000000-0000-4000-8000-000000000005",
                "control_fingerprint_before": "sha256:" + "6" * 64,
                "control_fingerprint_after": "sha256:" + "6" * 64,
                "deletion_completed_at": "2026-08-05T20:00:00+00:00",
                "rds_backup_retention_days": 7,
                "s3_noncurrent_retention_days": 30,
                "backup_expiry_at": "2026-08-12T20:00:00+00:00",
            },
        ),
        (
            "runtime-secret-rotation",
            {
                "api_secret_arn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:secret:ai-fde/api-AbCdEf"
                ),
                "migration_secret_arn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:"
                    "secret:ai-fde/migration-AbCdEf"
                ),
                "api_previous_version_id": "1" * 64,
                "api_current_version_id": "2" * 64,
                "migration_previous_version_id": "3" * 64,
                "migration_current_version_id": "4" * 64,
                "old_api_login_sqlstate": "28P01",
                "worker_group_role": "ai_fde_worker",
                "worker_group_login_state": "NOLOGIN",
                "retired_worker_database_user": "ai_fde_worker_0123456789ab",
                "current_worker_database_user": worker_database_user_for_release(
                    DEPLOYMENT_ID, REVISION
                ),
                "prior_worker_sessions_remaining": 0,
                "rotation_completed_at": NOW.isoformat(),
            },
        ),
    ],
)
def test_each_evidence_type_has_one_mandatory_typed_result_schema(
    evidence_type: str, results: dict[str, object]
) -> None:
    record = build_signed_evidence_record(
        record_id="evidence-2026-09-04-a",
        evidence_type=evidence_type,
        release_revision=REVISION,
        deployment_id=DEPLOYMENT_ID,
        completed_at=NOW,
        results=results,
        issuer_role_arn=ISSUER_ROLE_ARN,
        signing_key_arn=SIGNING_KEY_ARN,
        caller_principal_arn=ISSUER_PRINCIPAL_ARN,
        kms_client=FakeKMS(),
    )
    assert record["results"] == results

    invented = {**results, "caller_supplied_passed": True}
    with pytest.raises(EvidenceRecordError, match="mandatory schema"):
        build_signed_evidence_record(
            record_id="evidence-2026-09-04-a",
            evidence_type=evidence_type,
            release_revision=REVISION,
            deployment_id=DEPLOYMENT_ID,
            completed_at=NOW,
            results=invented,
            issuer_role_arn=ISSUER_ROLE_ARN,
            signing_key_arn=SIGNING_KEY_ARN,
            caller_principal_arn=ISSUER_PRINCIPAL_ARN,
            kms_client=FakeKMS(),
        )


def test_operator_sealers_reject_generic_outcomes_and_derive_release_claims() -> None:
    with pytest.raises(EvidenceRecordError, match="generic outcome field"):
        _reject_generic_result_claims({"status": "passed"})
    with pytest.raises(EvidenceRecordError, match="generic outcome field"):
        _reject_generic_result_claims({"nested": {"checks": ["looks-good"]}})

    deletion = _derive_results_from_observations(
        "deletion-boundary-rehearsal",
        {
            "engagement_id": "70000000-0000-4000-8000-000000000003",
            "deletion_receipt_id": "70000000-0000-4000-8000-000000000004",
            "application_rows_remaining": 0,
            "current_objects_remaining": 0,
            "object_versions_deleted": 2,
            "delete_markers_deleted": 1,
            "object_versions_remaining": 0,
            "delete_markers_remaining": 0,
            "control_engagement_id": "70000000-0000-4000-8000-000000000005",
            "control_fingerprint_before": "sha256:" + "6" * 64,
            "control_fingerprint_after": "sha256:" + "6" * 64,
            "deletion_completed_at": "2026-08-05T20:00:00+00:00",
            "rds_backup_retention_days": 7,
            "s3_noncurrent_retention_days": 30,
        },
        deployment_id=DEPLOYMENT_ID,
        release_revision=REVISION,
        completed_at=NOW,
    )
    assert deletion["backup_expiry_at"] == "2026-08-12T20:00:00+00:00"

    rotation = _derive_results_from_observations(
        "runtime-secret-rotation",
        {
            "api_secret_arn": (
                "arn:aws:secretsmanager:us-east-1:123456789012:secret:ai-fde/api-AbCdEf"
            ),
            "migration_secret_arn": (
                "arn:aws:secretsmanager:us-east-1:123456789012:"
                "secret:ai-fde/migration-AbCdEf"
            ),
            "api_previous_version_id": "1" * 64,
            "api_current_version_id": "2" * 64,
            "migration_previous_version_id": "3" * 64,
            "migration_current_version_id": "4" * 64,
            "old_api_login_sqlstate": "28P01",
            "worker_group_role": "ai_fde_worker",
            "worker_group_login_state": "NOLOGIN",
            "retired_worker_database_user": "ai_fde_worker_0123456789ab",
            "prior_worker_sessions_remaining": 0,
        },
        deployment_id=DEPLOYMENT_ID,
        release_revision=REVISION,
        completed_at=NOW,
    )
    assert rotation["current_worker_database_user"] == (
        worker_database_user_for_release(DEPLOYMENT_ID, REVISION)
    )
    assert rotation["rotation_completed_at"] == NOW.isoformat()

    forged_rotation = {
        key: value
        for key, value in rotation.items()
        if key not in {"current_worker_database_user", "rotation_completed_at"}
    }
    forged_rotation["old_api_login_sqlstate"] = "00000"
    with pytest.raises(EvidenceRecordError, match="authentication denial"):
        _derive_results_from_observations(
            "runtime-secret-rotation",
            forged_rotation,
            deployment_id=DEPLOYMENT_ID,
            release_revision=REVISION,
            completed_at=NOW,
        )


def test_prior_worker_sealer_accepts_explicit_empty_first_deployment() -> None:
    assert _derive_results_from_observations(
        "prior-worker-session-revocation",
        {"roles": []},
        deployment_id=DEPLOYMENT_ID,
        release_revision=REVISION,
        completed_at=NOW,
    ) == {"roles": []}


def test_prior_worker_sealer_rejects_deletion_before_session_ttl() -> None:
    cutoff = NOW - timedelta(hours=2)
    role = _prior_worker_role_observation(
        identity_state="deleted-after-ttl",
        deleted_at=(cutoff + timedelta(minutes=5)).isoformat(),
    )
    with pytest.raises(EvidenceRecordError, match="before TTL settled"):
        _derive_results_from_observations(
            "prior-worker-session-revocation",
            {"roles": [role]},
            deployment_id=DEPLOYMENT_ID,
            release_revision=REVISION,
            completed_at=NOW,
        )


def test_prior_worker_sealer_rejects_current_release_as_prior() -> None:
    role = _prior_worker_role_observation()
    role["prior_release_revision"] = REVISION
    role["prior_deployment_id"] = DEPLOYMENT_ID
    with pytest.raises(EvidenceRecordError, match="cannot equal the current"):
        _derive_results_from_observations(
            "prior-worker-session-revocation",
            {"roles": [role]},
            deployment_id=DEPLOYMENT_ID,
            release_revision=REVISION,
            completed_at=NOW,
        )


def test_prior_worker_sealer_rejects_observations_after_attestation() -> None:
    role = _prior_worker_role_observation(
        identity_state="deleted-after-ttl",
        deleted_at=(NOW + timedelta(seconds=1)).isoformat(),
    )
    with pytest.raises(EvidenceRecordError, match="cannot postdate"):
        _derive_results_from_observations(
            "prior-worker-session-revocation",
            {"roles": [role]},
            deployment_id=DEPLOYMENT_ID,
            release_revision=REVISION,
            completed_at=NOW,
        )


def test_prior_worker_sealer_requires_a_session_issued_before_the_cutoff() -> None:
    role = _prior_worker_role_observation()
    role["captured_session_issued_at"] = role["revocation_cutoff_at"]
    with pytest.raises(EvidenceRecordError, match="revocation timing is invalid"):
        _derive_results_from_observations(
            "prior-worker-session-revocation",
            {"roles": [role]},
            deployment_id=DEPLOYMENT_ID,
            release_revision=REVISION,
            completed_at=NOW,
        )


def test_prior_worker_sealer_rejects_a_probe_after_captured_session_expiry() -> None:
    role = _prior_worker_role_observation()
    role["live_probe_completed_at"] = role["captured_session_expires_at"]
    with pytest.raises(EvidenceRecordError, match="revocation timing is invalid"):
        _derive_results_from_observations(
            "prior-worker-session-revocation",
            {"roles": [role]},
            deployment_id=DEPLOYMENT_ID,
            release_revision=REVISION,
            completed_at=NOW,
        )


def _record() -> dict[str, Any]:
    return build_signed_evidence_record(
        record_id="restore-2026-09-04-a",
        evidence_type="isolated-restore-rehearsal",
        release_revision=REVISION,
        deployment_id=DEPLOYMENT_ID,
        completed_at=NOW - timedelta(hours=1),
        results=_results(),
        issuer_role_arn=ISSUER_ROLE_ARN,
        signing_key_arn=SIGNING_KEY_ARN,
        caller_principal_arn=ISSUER_PRINCIPAL_ARN,
        kms_client=FakeKMS(),
    )


def _write(path: Path, record: dict[str, Any]) -> None:
    path.write_text(json.dumps(record), encoding="utf-8")


def _load(path: Path, **overrides: Any) -> dict[str, object]:
    arguments: dict[str, Any] = {
        "expected_type": "isolated-restore-rehearsal",
        "expected_revision": REVISION,
        "expected_deployment_id": DEPLOYMENT_ID,
        "expected_issuer_role_arn": ISSUER_ROLE_ARN,
        "expected_signing_key_arn": SIGNING_KEY_ARN,
        "kms_client": FakeKMS(),
        "now": NOW,
    }
    arguments.update(overrides)
    return load_and_validate_evidence_record(path, **arguments)


def test_kms_signed_evidence_requires_exact_schema_release_results_and_provenance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "restore.json"
    record = _record()
    _write(path, record)

    result = _load(path)

    assert result == {
        "record_id": "restore-2026-09-04-a",
        "evidence_type": "isolated-restore-rehearsal",
        "status": "passed",
        "release_revision": REVISION,
        "deployment_id": DEPLOYMENT_ID,
        "completed_at": (NOW - timedelta(hours=1)).isoformat(),
        "content_digest": canonical_record_digest(record),
        "issuer_role_arn": ISSUER_ROLE_ARN,
        "signing_key_arn": SIGNING_KEY_ARN,
        "producer": "scripts.verify_isolated_restore",
        "attestation_mode": "machine-verified-kms-attestation",
        "signed_record": record,
    }


def test_invented_valid_looking_hash_or_signature_never_authenticates(tmp_path: Path) -> None:
    path = tmp_path / "invented.json"
    record = _record()
    record["signature"] = base64.b64encode(b"attacker-invented-signature" * 2).decode()
    _write(path, record)

    with pytest.raises(EvidenceRecordError, match="signature is invalid"):
        _load(path)


def test_wrong_issuer_key_and_tampering_are_rejected_offline(tmp_path: Path) -> None:
    path = tmp_path / "restore.json"
    record = _record()
    _write(path, record)

    with pytest.raises(EvidenceRecordError, match="role_arn"):
        _load(
            path,
            expected_issuer_role_arn="arn:aws:iam::123456789012:role/wrong-evidence-issuer",
        )
    with pytest.raises(EvidenceRecordError, match="signing_key_arn"):
        _load(
            path,
            expected_signing_key_arn=(
                "arn:aws:kms:us-east-1:123456789012:"
                "key/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            ),
        )

    record["results"]["target_identifier"] = "ai-fde-restore-tampered"
    _write(path, record)
    with pytest.raises(EvidenceRecordError, match="does not match its content"):
        _load(path)

    record["content_digest"] = canonical_record_digest(record)
    _write(path, record)
    with pytest.raises(EvidenceRecordError, match="signature is invalid"):
        _load(path)


def test_wrong_per_type_schema_failed_claim_and_wrong_version_are_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "restore.json"
    record = _record()
    del record["results"]["digest_matched"]
    record["content_digest"] = canonical_record_digest(record)
    _write(path, record)
    with pytest.raises(EvidenceRecordError, match="mandatory schema"):
        _load(path)

    record = _record()
    record["results"]["digest_matched"] = False
    record["content_digest"] = canonical_record_digest(record)
    _write(path, record)
    with pytest.raises(EvidenceRecordError, match="isolated match"):
        _load(path)

    record = _record()
    record["attestation_mode"] = "trusted-operator-kms-attestation"
    record["content_digest"] = canonical_record_digest(record)
    _write(path, record)
    with pytest.raises(EvidenceRecordError, match="attestation_mode"):
        _load(path)

    record = _record()
    record["schema_version"] = "fdlc.production-qualification-evidence/v1"
    record["content_digest"] = canonical_record_digest(record)
    _write(path, record)
    with pytest.raises(EvidenceRecordError, match="schema_version"):
        _load(path)


def test_stale_duplicate_and_synthetic_records_cannot_enter_production(tmp_path: Path) -> None:
    path = tmp_path / "restore.json"
    record = _record()
    record["completed_at"] = (NOW - timedelta(days=31)).isoformat()
    record["content_digest"] = canonical_record_digest(record)
    _write(path, record)
    with pytest.raises(EvidenceRecordError, match="older"):
        _load(path)

    path.write_text(
        '{"schema_version":"'
        + EVIDENCE_SCHEMA_VERSION
        + '","schema_version":"duplicate"}',
        encoding="utf-8",
    )
    with pytest.raises(EvidenceRecordError, match="unambiguous JSON"):
        _load(path)

    synthetic = build_synthetic_evidence_record(
        environment="test",
        record_id="restore-2026-09-04-a",
        evidence_type="isolated-restore-rehearsal",
        release_revision=REVISION,
        deployment_id=DEPLOYMENT_ID,
        completed_at=NOW,
        checks=[{"name": "invented", "status": "passed"}],
    )
    _write(path, synthetic)
    with pytest.raises(EvidenceRecordError, match="authenticated v2 schema"):
        _load(path)


def test_builder_rejects_untrusted_role_and_ambiguous_values() -> None:
    with pytest.raises(EvidenceRecordError, match="configured issuer role"):
        build_signed_evidence_record(
            record_id="restore-2026-09-04-a",
            evidence_type="isolated-restore-rehearsal",
            release_revision=REVISION,
            deployment_id=DEPLOYMENT_ID,
            completed_at=NOW,
            results=_results(),
            issuer_role_arn=ISSUER_ROLE_ARN,
            signing_key_arn=SIGNING_KEY_ARN,
            caller_principal_arn="arn:aws:sts::123456789012:assumed-role/deployer/session",
            kms_client=FakeKMS(),
        )

    with pytest.raises(EvidenceRecordError, match="include an offset"):
        build_signed_evidence_record(
            record_id="restore-2026-09-04-a",
            evidence_type="isolated-restore-rehearsal",
            release_revision=REVISION,
            deployment_id=DEPLOYMENT_ID,
            completed_at=datetime(2026, 9, 4, 20, 0),
            results=_results(),
            issuer_role_arn=ISSUER_ROLE_ARN,
            signing_key_arn=SIGNING_KEY_ARN,
            caller_principal_arn=ISSUER_PRINCIPAL_ARN,
            kms_client=FakeKMS(),
        )

    with pytest.raises(EvidenceRecordError, match="only in development or test"):
        build_synthetic_evidence_record(
            environment="production",
            record_id="restore-2026-09-04-a",
            evidence_type="isolated-restore-rehearsal",
            release_revision=REVISION,
            deployment_id=DEPLOYMENT_ID,
            completed_at=NOW,
            checks=[{"name": "invented", "status": "passed"}],
        )
