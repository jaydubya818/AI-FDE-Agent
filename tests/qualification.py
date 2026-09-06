from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils

from ai_fde.modules.factory_engineer.canonical import canonical_sha256
from ai_fde.modules.identity.database import worker_database_user_for_release
from ai_fde.modules.runtime.qualification import (
    QUALIFICATION_SCHEMA_VERSION,
    qualification_content_digest,
    readiness_validation_digest,
)

DEFAULT_WORKER_OPERATOR_ID = UUID("00000000-0000-4000-8000-000000000002")
DEFAULT_WORKER_ENGAGEMENT_ID = UUID("00000000-0000-4000-8000-000000000003")

_TEST_EVIDENCE_PRIVATE_KEY = rsa.generate_private_key(
    public_exponent=65537,
    key_size=3072,
)
_TEST_EVIDENCE_PUBLIC_DER = _TEST_EVIDENCE_PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
TEST_EVIDENCE_PUBLIC_KEY_DER_B64 = base64.b64encode(
    _TEST_EVIDENCE_PUBLIC_DER
).decode("ascii")
TEST_EVIDENCE_PUBLIC_KEY_B64_SHA256 = (
    "sha256:"
    + hashlib.sha256(TEST_EVIDENCE_PUBLIC_KEY_DER_B64.encode("ascii")).hexdigest()
)


def resign_test_evidence_envelope(envelope: dict[str, Any]) -> None:
    """Re-sign a mutated fixture to exercise runtime semantic validation."""

    unsigned = dict(envelope)
    unsigned.pop("content_digest", None)
    unsigned.pop("signature", None)
    digest = canonical_sha256(unsigned)
    signature = _TEST_EVIDENCE_PRIVATE_KEY.sign(
        bytes.fromhex(digest.removeprefix("sha256:")),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256.digest_size,
        ),
        utils.Prehashed(hashes.SHA256()),
    )
    envelope["content_digest"] = digest
    envelope["signature"] = base64.b64encode(signature).decode("ascii")


def _evidence_results(
    evidence_type: str,
    *,
    validated_at: datetime,
    worker_engagement_id: UUID,
    worker_database_user: str,
    application_origin: str,
    oidc_issuer_url: str,
) -> dict[str, Any]:
    if evidence_type == "auth0-live-validation":
        return {
            "issuer_url": oidc_issuer_url,
            "callback_url": f"{application_origin}/api/auth/callback",
            "authorization_request_id": "00000000-0000-4000-8000-000000000011",
            "authorization_code_challenge_method": "S256",
            "authorization_response_type": "code",
            "allowlisted_callback_request_id": "00000000-0000-4000-8000-000000000012",
            "allowlisted_callback_status_code": 303,
            "unallowlisted_callback_request_id": "00000000-0000-4000-8000-000000000013",
            "unallowlisted_callback_status_code": 403,
            "logout_request_id": "00000000-0000-4000-8000-000000000014",
            "logout_status_code": 204,
            "revoked_session_request_id": "00000000-0000-4000-8000-000000000015",
            "revoked_session_status_code": 401,
        }
    if evidence_type == "isolated-restore-rehearsal":
        return {
            "source_identifier": "source-restore-record",
            "target_identifier": "target-restore-record",
            "database_role": "ai_fde_app",
            "audit_event_id": "00000000-0000-4000-8000-000000000021",
            "audit_fingerprint": "sha256:" + "1" * 64,
            "digest_subject_type": "deployment-package",
            "digest_subject_id": "00000000-0000-4000-8000-000000000022",
            "stored_digest": "sha256:" + "2" * 64,
            "row_fingerprint": "sha256:" + "3" * 64,
            "source_target_isolated": True,
            "durable_record_matched": True,
            "digest_matched": True,
        }
    if evidence_type == "deletion-boundary-rehearsal":
        deleted_at = validated_at - timedelta(hours=1)
        return {
            "engagement_id": "00000000-0000-4000-8000-000000000031",
            "deletion_receipt_id": "00000000-0000-4000-8000-000000000032",
            "application_rows_remaining": 0,
            "current_objects_remaining": 0,
            "object_versions_deleted": 1,
            "delete_markers_deleted": 1,
            "object_versions_remaining": 0,
            "delete_markers_remaining": 0,
            "control_engagement_id": "00000000-0000-4000-8000-000000000033",
            "control_fingerprint_before": "sha256:" + "4" * 64,
            "control_fingerprint_after": "sha256:" + "4" * 64,
            "deletion_completed_at": deleted_at.isoformat(),
            "rds_backup_retention_days": 7,
            "s3_noncurrent_retention_days": 7,
            "backup_expiry_at": (deleted_at + timedelta(days=7)).isoformat(),
        }
    if evidence_type == "runtime-secret-rotation":
        return {
            "api_secret_arn": "arn:aws:secretsmanager:us-east-1:123456789012:secret:api",
            "migration_secret_arn": (
                "arn:aws:secretsmanager:us-east-1:123456789012:secret:migration"
            ),
            "api_previous_version_id": "a" * 32,
            "api_current_version_id": "b" * 32,
            "migration_previous_version_id": "c" * 32,
            "migration_current_version_id": "d" * 32,
            "old_api_login_sqlstate": "28P01",
            "worker_group_role": "ai_fde_worker",
            "worker_group_login_state": "NOLOGIN",
            "retired_worker_database_user": "ai_fde_worker_000000000000",
            "current_worker_database_user": worker_database_user,
            "prior_worker_sessions_remaining": 0,
            "rotation_completed_at": validated_at.isoformat(),
        }
    if evidence_type == "prior-worker-session-revocation":
        cutoff = validated_at - timedelta(hours=2)
        session_expiry = cutoff + timedelta(seconds=3660)
        return {
            "roles": [
                {
                    "role_arn": "arn:aws:iam::123456789012:role/ai-fde-worker-prior",
                    "prior_release_revision": "9" * 40,
                    "prior_deployment_id": "qualification-prior",
                    "identity_state": "retained-quarantined",
                    "quarantine_control": "inline-deny-pre-cutoff-sessions",
                    "quarantine_policy_digest": "sha256:" + "5" * 64,
                    "assume_role_disabled": True,
                    "permission_grants_stripped": True,
                    "quarantine_applied_at": cutoff.isoformat(),
                    "revocation_cutoff_at": cutoff.isoformat(),
                    "session_expiry_not_before": session_expiry.isoformat(),
                    "max_session_duration_seconds": 3600,
                    "propagation_wait_seconds": 60,
                    "captured_session_issued_at": (
                        cutoff - timedelta(minutes=1)
                    ).isoformat(),
                    "captured_session_expires_at": (
                        cutoff + timedelta(minutes=59)
                    ).isoformat(),
                    "live_probe_completed_at": (
                        cutoff + timedelta(seconds=60)
                    ).isoformat(),
                    "deleted_at": None,
                    "targets": {
                        "db_user_arn": (
                            "arn:aws:rds-db:us-east-1:123456789012:"
                            "dbuser/db-ABCDEFGHIJKLMNOPQRSTUVWXY/"
                            f"{worker_database_user}"
                        ),
                        "s3_object_prefix_arn": (
                            "arn:aws:s3:::ai-fde-evidence/engagements/"
                            f"{worker_engagement_id}/*"
                        ),
                        "kms_key_arn": (
                            "arn:aws:kms:us-east-1:123456789012:"
                            "key/12345678-1234-1234-1234-123456789099"
                        ),
                        "bedrock_model_arn": (
                            "arn:aws:bedrock:us-east-1::"
                            "foundation-model/profile-v1"
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
            ]
        }
    raise AssertionError(f"Unhandled evidence type {evidence_type}")


def _signed_evidence_summary(
    *,
    label: str,
    evidence_type: str,
    producer: str,
    attestation_mode: str,
    release_revision: str,
    deployment_id: str,
    validated_at: datetime,
    issuer_role_arn: str,
    signing_key_arn: str,
    results: dict[str, Any],
) -> dict[str, Any]:
    outcome = "checks-passed" if label == "restore" else "observations-attested"
    envelope: dict[str, Any] = {
        "schema_version": "fdlc.production-qualification-evidence/v2",
        "record_id": f"{label}-evidence-record",
        "evidence_type": evidence_type,
        "release_revision": release_revision,
        "deployment_id": deployment_id,
        "completed_at": validated_at.isoformat(),
        "attestation_mode": attestation_mode,
        "attestation_outcome": outcome,
        "issuer": {
            "role_arn": issuer_role_arn,
            "signing_key_arn": signing_key_arn,
            "signing_algorithm": "RSASSA_PSS_SHA_256",
            "producer": producer,
        },
        "results": results,
    }
    digest = canonical_sha256(envelope)
    signature = _TEST_EVIDENCE_PRIVATE_KEY.sign(
        bytes.fromhex(digest.removeprefix("sha256:")),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256.digest_size,
        ),
        utils.Prehashed(hashes.SHA256()),
    )
    envelope["content_digest"] = digest
    envelope["signature"] = base64.b64encode(signature).decode("ascii")
    return {
        "record_id": envelope["record_id"],
        "evidence_type": evidence_type,
        "status": "passed",
        "release_revision": release_revision,
        "deployment_id": deployment_id,
        "completed_at": validated_at.isoformat(),
        "content_digest": digest,
        "issuer_role_arn": issuer_role_arn,
        "signing_key_arn": signing_key_arn,
        "producer": producer,
        "attestation_mode": attestation_mode,
        "signed_record": envelope,
    }


def build_qualification_record(
    *,
    release_revision: str = "a" * 40,
    deployment_id: str = "qualification-test",
    worker_operator_id: UUID = DEFAULT_WORKER_OPERATOR_ID,
    worker_engagement_id: UUID = DEFAULT_WORKER_ENGAGEMENT_ID,
    qualifier_role_arn: str = "arn:aws:iam::123456789012:role/ai-fde-qualifier",
    application_origin: str = "https://cockpit.example.com",
    oidc_issuer_url: str = "https://tenant.us.auth0.com/",
    oidc_client_id: str = "client-id",
    oidc_allowed_emails: list[str] | None = None,
    now: datetime | None = None,
) -> tuple[str, str]:
    validated_at = now or datetime.now(UTC)
    allowed_emails = oidc_allowed_emails or ["fde@example.com"]
    worker_database_user = worker_database_user_for_release(
        deployment_id, release_revision
    )
    evidence_issuer_role_arn = "arn:aws:iam::123456789012:role/ai-fde-evidence-issuer"
    evidence_signing_key_arn = (
        "arn:aws:kms:us-east-1:123456789012:"
        "key/12345678-1234-1234-1234-123456789012"
    )
    evidence_contract = {
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
    external_evidence = {
        label: _signed_evidence_summary(
            label=label,
            evidence_type=evidence_type,
            producer=producer,
            attestation_mode=attestation_mode,
            release_revision=release_revision,
            deployment_id=deployment_id,
            validated_at=validated_at,
            issuer_role_arn=evidence_issuer_role_arn,
            signing_key_arn=evidence_signing_key_arn,
            results=_evidence_results(
                evidence_type,
                validated_at=validated_at,
                worker_engagement_id=worker_engagement_id,
                worker_database_user=worker_database_user,
                application_origin=application_origin,
                oidc_issuer_url=oidc_issuer_url,
            ),
        )
        for label, (evidence_type, producer, attestation_mode) in evidence_contract.items()
    }
    cluster = "ai-fde-design-partner"
    task_role_arns = {
        runtime: (
            "arn:aws:iam::123456789012:role/ai-fde-worker-current"
            if runtime == "worker"
            else f"arn:aws:iam::123456789012:role/ai-fde-{runtime}-task"
        )
        for runtime in ("web", "api", "worker", "migration")
    }
    execution_role_arns = {
        runtime: f"arn:aws:iam::123456789012:role/ai-fde-{runtime}-execution"
        for runtime in ("web", "api", "worker", "migration")
    }
    service_inventory: dict[str, dict[str, Any]] = {
        runtime: {
            "service": f"ai-fde-{runtime}",
            "task_definition_arn": (
                "arn:aws:ecs:us-east-1:123456789012:"
                f"task-definition/ai-fde-{runtime}:42"
            ),
            "desired_count": 1,
            "running_task_arns": [
                "arn:aws:ecs:us-east-1:123456789012:"
                f"task/{cluster}/{index:032x}"
            ],
            "stopped_task_arns": [],
        }
        for index, runtime in enumerate(("web", "api", "worker"), start=1)
    }
    revocation_digest = external_evidence["prior_worker_revocation"]["content_digest"]
    record: dict[str, Any] = {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "validated_at": validated_at.isoformat(),
        "expires_at": (validated_at + timedelta(hours=24)).isoformat(),
        "aws_account_id": "123456789012",
        "aws_principal_arn": qualifier_role_arn.replace(":iam:", ":sts:").replace(
            ":role/", ":assumed-role/"
        )
        + "/test-session",
        "region": "us-east-1",
        "status": "passed",
        "release": {
            "git_commit": release_revision,
            "deployment_id": deployment_id,
            "qualification_mode": "controlled-design-partner",
            "worker_operator_id": str(worker_operator_id),
            "worker_engagement_id": str(worker_engagement_id),
            "worker_database_user": worker_database_user,
            "application_origin": application_origin,
            "oidc_issuer_url": oidc_issuer_url,
            "oidc_client_id": oidc_client_id,
            "oidc_allowed_emails": allowed_emails,
            "evidence_issuer_role_arn": evidence_issuer_role_arn,
            "evidence_signing_key_arn": evidence_signing_key_arn,
            "evidence_signing_public_key_der_b64": TEST_EVIDENCE_PUBLIC_KEY_DER_B64,
            "evidence_signing_public_key_b64_sha256": (
                TEST_EVIDENCE_PUBLIC_KEY_B64_SHA256
            ),
            "bedrock_model_id": "profile-v1",
            "bedrock_model_arn": (
                "arn:aws:bedrock:us-east-1::foundation-model/profile-v1"
            ),
            "bedrock_allowed_data_classifications": ["INTERNAL", "PUBLIC"],
            "images": {
                "web": "example/web@sha256:" + "a" * 64,
                "api": "example/api@sha256:" + "b" * 64,
                "worker": "example/worker@sha256:" + "c" * 64,
                "migration": "example/api@sha256:" + "b" * 64,
            },
            "task_role_arns": task_role_arns,
            "execution_role_arns": execution_role_arns,
        },
        "external_evidence": external_evidence,
        "checks": {
            "https": {"status": "passed"},
            "s3": {
                "status": "passed",
                "bucket": "ai-fde-evidence",
                "encryption": "aws:kms",
                "kms_key_arn": (
                    "arn:aws:kms:us-east-1:123456789012:"
                    "key/12345678-1234-1234-1234-123456789099"
                ),
                "bucket_policy_sha256": "sha256:" + "6" * 64,
                "secure_transport_required": True,
                "explicit_sse_kms_headers_required": True,
                "versioning": "Enabled",
                "noncurrent_retention_days": 7,
            },
            "rds": {
                "status": "passed",
                "identifier": "ai-fde-postgres",
                "multi_az": True,
                "backup_retention_days": 7,
                "latest_restorable_time": (
                    validated_at - timedelta(minutes=5)
                ).isoformat(),
                "maximum_rpo_minutes": 15,
                "iam_database_authentication": "enabled",
                "db_resource_id": "db-ABCDEFGHIJKLMNOPQRSTUVWXY",
                "endpoint_address": "db.example.us-east-1.rds.amazonaws.com",
                "endpoint_port": 5432,
                "database_name": "ai_fde",
                "engine": "postgres",
                "vpc_id": "vpc-11111111",
                "database_subnet_ids": ["subnet-11111111", "subnet-22222222"],
                "security_group_ids": ["sg-11111111"],
                "storage_encrypted": True,
                "kms_key_arn": (
                    "arn:aws:kms:us-east-1:123456789012:"
                    "key/12345678-1234-1234-1234-123456789098"
                ),
                "publicly_accessible": False,
                "deletion_protection": True,
                "force_ssl": True,
                "ca_bundle_path": "/opt/ai-fde/certs/aws-rds-global-bundle.pem",
                "ca_bundle_sha256": (
                    "sha256:e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
                ),
            },
            "ecs": {
                "status": "passed",
                "task_role_arns": task_role_arns,
                "execution_role_arns": execution_role_arns,
            },
            "ecs_data_role_inventory": {
                "status": "passed",
                "task_role_arns": task_role_arns,
                "execution_role_arns": execution_role_arns,
                "roles": {
                    role_kind: {
                        "role_arn": role_arn,
                        "trust_policy_sha256": "sha256:" + digest_char * 64,
                        "inline_policy_sha256": {
                            policy_name: "sha256:" + digest_char * 64
                        },
                        "attached_managed_policy_arns": (
                            [
                                "arn:aws:iam::aws:policy/service-role/"
                                "AmazonECSTaskExecutionRolePolicy"
                            ]
                            if role_kind.endswith("_execution")
                            else []
                        ),
                        "permissions_boundary_present": False,
                        "instance_profile_arns": [],
                    }
                    for role_kind, role_arn, policy_name, digest_char in (
                        (
                            "api_task",
                            task_role_arns["api"],
                            "evidence-objects",
                            "b",
                        ),
                        (
                            "api_execution",
                            execution_role_arns["api"],
                            "runtime-secret",
                            "c",
                        ),
                        (
                            "migration_task",
                            task_role_arns["migration"],
                            "package-retrieval-secret-delivery",
                            "d",
                        ),
                        (
                            "migration_execution",
                            execution_role_arns["migration"],
                            "runtime-secret",
                            "e",
                        ),
                    )
                },
            },
            "worker_network": {
                "status": "passed",
                "vpc_id": "vpc-11111111",
                "worker_security_group_id": "sg-22222222",
                "endpoint_security_group_id": "sg-77777777",
                "endpoint_ingress_security_group_ids": [
                    "sg-22222222",
                    "sg-33333333",
                    "sg-44444444",
                    "sg-55555555",
                ],
                "endpoint_ingress_rule_count": 4,
                "worker_subnet_ids": ["subnet-33333333", "subnet-44444444"],
                "worker_route_table_id": "rtb-55555555",
                "allowed_egress_rule_count": 5,
                "public_or_nat_routes": 0,
                "vpc_endpoints": {
                    name: {
                        "id": f"vpce-{index:08x}",
                        "service_name": f"com.amazonaws.us-east-1.{name}",
                        "type": "Gateway" if name == "s3" else "Interface",
                        "policy_sha256": "sha256:" + f"{index:x}" * 64,
                        **(
                            {
                                "route_table_ids": [
                                    "rtb-55555555",
                                    "rtb-66666666",
                                ]
                            }
                            if name == "s3"
                            else {
                                "subnet_ids": [
                                    "subnet-11111111",
                                    "subnet-22222222",
                                ],
                                "security_group_ids": ["sg-77777777"],
                            }
                        ),
                    }
                    for index, name in enumerate(
                        (
                            "s3",
                            "secretsmanager",
                            "bedrock-runtime",
                            "ecr.api",
                            "ecr.dkr",
                            "logs",
                        ),
                        start=1,
                    )
                },
            },
            "worker_s3_isolation": {
                "status": "passed",
                "worker_engagement_id": str(worker_engagement_id),
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
            },
            "worker_bedrock_isolation": {
                "status": "passed",
                "configured_model_arn": (
                    "arn:aws:bedrock:us-east-1::foundation-model/profile-v1"
                ),
                "configured_model_invoke": "allowed",
                "alternate_model_invoke": "denied",
                "alternate_region_model_invoke": "denied",
            },
            "worker_database_identity": {
                "status": "passed",
                "worker_role_arn": task_role_arns["worker"],
                "db_user_arn": (
                    "arn:aws:rds-db:us-east-1:123456789012:"
                    f"dbuser/db-ABCDEFGHIJKLMNOPQRSTUVWXY/{worker_database_user}"
                ),
                "worker_connect": "allowed",
                "non_worker_connect": "denied",
            },
            "bedrock_logging": {"status": "passed"},
            "bedrock_evaluation": {"status": "passed"},
            "runtime_secrets": {
                runtime_name: {
                    "status": "passed",
                    "secret_arn": (
                        "arn:aws:secretsmanager:us-east-1:123456789012:"
                        f"secret:{runtime_name}"
                    ),
                    "last_changed": (
                        validated_at - timedelta(hours=3)
                    ).isoformat(),
                    "maximum_age_days": 90,
                    "current_version_id": (
                        "b" * 32 if runtime_name == "api" else "d" * 32
                    ),
                    "current_version_created_at": (
                        validated_at - timedelta(hours=3)
                    ).isoformat(),
                    "awscurrent_count": 1,
                    "observed_version_count": 2,
                    "task_definition_registered_at": (
                        validated_at - timedelta(hours=2)
                    ).isoformat(),
                    "ecs_value_from": {
                        name: (
                            "arn:aws:secretsmanager:us-east-1:123456789012:"
                            f"secret:{runtime_name}:{name}::"
                            f"{'b' * 32 if runtime_name == 'api' else 'd' * 32}"
                        )
                        for name in (
                            ("AI_FDE_DATABASE_URL", "AI_FDE_OIDC_CLIENT_SECRET")
                            if runtime_name == "api"
                            else (
                                "AI_FDE_MIGRATION_DATABASE_URL",
                                "AI_FDE_APP_DATABASE_PASSWORD",
                            )
                        )
                    },
                }
                for runtime_name in ("api", "migration")
            },
            "qualification_secret_boundary": {
                "status": "passed",
                "secret_arn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:"
                    "secret:ai-fde/qualification-AbCdEf"
                ),
                "only_writer_role_arn": qualifier_role_arn,
                "policy_sha256": "sha256:" + "7" * 64,
            },
            "qualification_control_plane": {
                "status": "passed",
                "qualification_secret_arn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:"
                    "secret:ai-fde/qualification-AbCdEf"
                ),
                "signing_key_arn": evidence_signing_key_arn,
                "roles": {
                    role_kind: {
                        "role_arn": role_arn,
                        "trusted_principal_arn": (
                            "arn:aws:iam::123456789012:"
                            f"role/{role_kind}-principal"
                        ),
                        "trust_policy_sha256": "sha256:" + digest_char * 64,
                        "inline_policy_sha256": {
                            policy_name: "sha256:" + digest_char * 64
                        },
                        "attached_managed_policy_arns": [],
                        "instance_profile_arns": [],
                        "permissions_boundary_present": False,
                    }
                    for role_kind, role_arn, policy_name, digest_char in (
                        (
                            "qualifier",
                            qualifier_role_arn,
                            "deployment-qualification",
                            "8",
                        ),
                        (
                            "deployment",
                            "arn:aws:iam::123456789012:role/ai-fde-deployment",
                            "release",
                            "9",
                        ),
                        (
                            "evidence_issuer",
                            evidence_issuer_role_arn,
                            "sign-qualification-evidence",
                            "a",
                        ),
                    )
                },
                "simulations": {
                    **{
                        f"{role_kind}_{action}": (
                            "allowed"
                            if role_kind == "qualifier"
                            and action == "PutSecretValue"
                            else "denied"
                        )
                        for role_kind in (
                            "qualifier",
                            "deployment",
                            "evidence_issuer",
                        )
                        for action in (
                            "DeleteResourcePolicy",
                            "DeleteSecret",
                            "PutResourcePolicy",
                            "PutSecretValue",
                            "RotateSecret",
                            "UpdateSecret",
                            "UpdateSecretVersionStage",
                        )
                    },
                    "qualifier_kms_sign": "denied",
                    "deployment_kms_sign": "denied",
                    "evidence_issuer_kms_sign": "allowed",
                },
            },
            "prior_worker_identity_denials": {
                "status": "passed",
                "first_deployment": False,
                "revocation_evidence_content_digest": revocation_digest,
                "roles": [
                    {
                        "role_arn": (
                            "arn:aws:iam::123456789012:role/ai-fde-worker-prior"
                        ),
                        "identity_state": "retained-quarantined",
                        "iam_get_role": "present",
                        "revocation_cutoff_at": (
                            validated_at - timedelta(hours=2)
                        ).isoformat(),
                        "live_probe_completed_at": (
                            validated_at - timedelta(hours=2) + timedelta(seconds=60)
                        ).isoformat(),
                        "deleted_at": None,
                        "live_quarantine": {
                            "quarantine_control": (
                                "inline-deny-pre-cutoff-sessions"
                            ),
                            "quarantine_policy_name": "AWSRevokeOlderSessions",
                            "quarantine_policy_digest": "sha256:" + "5" * 64,
                            "revocation_cutoff_at": (
                                validated_at - timedelta(hours=2)
                            ).isoformat(),
                            "max_session_duration_seconds": 3600,
                            "assume_role_disabled": True,
                            "sole_inline_policy": True,
                            "attached_managed_policy_count": 0,
                            "permissions_boundary_present": False,
                            "instance_profile_count": 0,
                        },
                        "rds_db_connect": "denied",
                        "s3_get_current_prefix": "denied",
                        "s3_put_current_prefix": "denied",
                        "kms_decrypt_current_key": "denied",
                        "kms_generate_data_key_current_key": "denied",
                        "bedrock_invoke_current_model": "denied",
                    }
                ],
            },
            "standalone_task_drain": {
                "status": "passed",
                "cluster": cluster,
                "services": service_inventory,
                "cluster_running_task_arns": sorted(
                    task_arn
                    for service in service_inventory.values()
                    for task_arn in service["running_task_arns"]
                ),
                "cluster_stopped_task_history": [],
                "enumerated_desired_statuses": ["RUNNING", "STOPPED"],
                "migration_task_definition_arn": (
                    "arn:aws:ecs:us-east-1:123456789012:"
                    "task-definition/ai-fde-migration:42"
                ),
                "migration_tasks": [],
            },
        },
    }
    record["validation_id"] = readiness_validation_digest(record)
    record["content_digest"] = qualification_content_digest(record)
    version_id = str(record["validation_id"]).removeprefix("sha256:")
    return json.dumps(record, sort_keys=True, separators=(",", ":")), version_id
