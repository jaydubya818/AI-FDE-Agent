from __future__ import annotations

import hashlib
import json
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from ai_fde.modules.identity.database import worker_database_user_for_release
from scripts.verify_design_partner_activation import (
    _verify_current_worker_iam_boundaries,
    _verify_ecs_role_transition,
    _verify_runtime_secret_transition,
    _verify_standalone_task_drain_transition,
)
from scripts.verify_design_partner_readiness import (
    RDS_CA_BUNDLE_PATH,
    RDS_CA_BUNDLE_SHA256,
    ReadinessFailure,
    _bind_runtime_secrets_to_ecs,
    _canonical_policy_digest,
    _publish_qualification_record,
    _release_inputs,
    _verify_bedrock_evaluation,
    _verify_ecs,
    _verify_ecs_data_role_inventory,
    _verify_https,
    _verify_prior_worker_identity_denials,
    _verify_qualification_control_plane,
    _verify_qualification_secret_boundary,
    _verify_rds,
    _verify_s3,
    _verify_secret,
    _verify_standalone_task_drain,
    _verify_worker_bedrock_isolation,
    _verify_worker_database_identity,
    _verify_worker_network,
    _verify_worker_s3_isolation,
    readiness_validation_digest,
)

WORKER_ENGAGEMENT_ID = "70000000-0000-4000-8000-000000000001"
WORKER_OPERATOR_ID = "70000000-0000-4000-8000-000000000002"
QUALIFIER_ROLE_ARN = "arn:aws:iam::123456789012:role/ai-fde-qualifier"
EVIDENCE_ISSUER_ROLE_ARN = "arn:aws:iam::123456789012:role/ai-fde-evidence-issuer"
DEPLOYMENT_ROLE_ARN = "arn:aws:iam::123456789012:role/ai-fde-deployment"
EVIDENCE_SIGNING_KEY_ARN = (
    "arn:aws:kms:us-east-1:123456789012:key/70000000-0000-4000-8000-000000000008"
)
WORKER_TASK_ROLE_ARN = "arn:aws:iam::123456789012:role/worker-task"
TASK_ROLE_ARNS = {
    "web": "arn:aws:iam::123456789012:role/web-task",
    "api": "arn:aws:iam::123456789012:role/api-task",
    "worker": WORKER_TASK_ROLE_ARN,
    "migration": "arn:aws:iam::123456789012:role/migration-task",
}
EXECUTION_ROLE_ARNS = {
    runtime: f"arn:aws:iam::123456789012:role/{runtime}-execution"
    for runtime in ("web", "api", "worker", "migration")
}
PRIOR_RELEASE_REVISION = "9" * 40
PRIOR_DEPLOYMENT_ID = "deploy-2026-08-01-a"
PRIOR_WORKER_ROLE_SUFFIX = hashlib.sha256(
    f"{PRIOR_DEPLOYMENT_ID}:{PRIOR_RELEASE_REVISION}".encode()
).hexdigest()[:12]
PRIOR_WORKER_TASK_ROLE_ARN = (
    "arn:aws:iam::123456789012:role/"
    f"ai-fde-worker-{PRIOR_WORKER_ROLE_SUFFIX}-task"
)
WORKER_DATABASE_USER = worker_database_user_for_release(
    "deploy-2026-09-04-a", "a" * 40
)
WORKER_DATABASE_URL = (
    f"postgresql+psycopg://{WORKER_DATABASE_USER}@db.example.us-east-1.rds.amazonaws.com:"
    f"5432/ai_fde?sslmode=verify-full&sslrootcert={RDS_CA_BUNDLE_PATH}"
)
EVIDENCE_BUCKET_ARN = "arn:aws:s3:::ai-fde-evidence"
EVIDENCE_KMS_KEY_ARN = "arn:aws:kms:us-east-1:123456789012:key/70000000-0000-4000-8000-000000000009"
BEDROCK_MODEL_ARN = "arn:aws:bedrock:us-east-1::foundation-model/profile-v1"
SECRET_VERSION_IDS = {"api": "b" * 32, "migration": "c" * 32}
MIGRATION_TASK_DEFINITION_ARN = (
    "arn:aws:ecs:us-east-1:123456789012:task-definition/ai-fde-migration:1"
)


def _test_quarantine_policy(cutoff: datetime) -> dict[str, object]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "RevokeOlderSessions",
                "Effect": "Deny",
                "Action": "*",
                "Resource": "*",
                "Condition": {
                    "DateLessThan": {
                        "aws:TokenIssueTime": cutoff.isoformat().replace("+00:00", "Z")
                    }
                },
            }
        ],
    }


def test_validation_identity_is_a_deterministic_digest_without_self_reference() -> None:
    record: dict[str, Any] = {
        "schema_version": "design-partner-readiness-v3",
        "validated_at": "2026-09-04T20:00:00+00:00",
        "status": "passed",
        "release": {"git_commit": "a" * 40},
        "checks": {"https": {"status": "passed"}},
    }

    validation_id = readiness_validation_digest(record)
    record["validation_id"] = validation_id
    record["content_digest"] = "sha256:" + ("f" * 64)

    assert validation_id.startswith("sha256:")
    assert len(validation_id) == 71
    assert readiness_validation_digest(record) == validation_id

    record["release"] = {"git_commit": "b" * 40}
    assert readiness_validation_digest(record) != validation_id


class FakeQualificationSecret:
    def __init__(
        self,
        *,
        allowed_role_arn: str = QUALIFIER_ROLE_ARN,
        mutation: str | None = None,
    ) -> None:
        self.allowed_role_arn = allowed_role_arn
        self.mutation = mutation

    def describe_secret(self, *, SecretId: str) -> dict[str, object]:
        return {"ARN": SecretId}

    def get_resource_policy(self, *, SecretId: str) -> dict[str, str]:
        resource = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:other"
            if self.mutation == "resource"
            else SecretId
        )
        statements: list[dict[str, object]] = [
            {
                "Sid": "DenyQualificationWritesOutsideQualifier",
                "Effect": "Deny",
                "Principal": {"AWS": "*"},
                "Action": [
                    "secretsmanager:DeleteResourcePolicy",
                    "secretsmanager:DeleteSecret",
                    "secretsmanager:PutResourcePolicy",
                    "secretsmanager:PutSecretValue",
                    "secretsmanager:RotateSecret",
                    "secretsmanager:UpdateSecret",
                    "secretsmanager:UpdateSecretVersionStage",
                ],
                "Resource": resource,
                "Condition": {
                    "ArnNotEquals": {
                        "aws:PrincipalArn": self.allowed_role_arn,
                    }
                },
            }
        ]
        if self.mutation == "extra":
            statements.append(
                {
                    "Sid": "UnexpectedAllow",
                    "Effect": "Allow",
                    "Principal": {"AWS": "*"},
                    "Action": "secretsmanager:GetSecretValue",
                    "Resource": SecretId,
                }
            )
        return {
            "ResourcePolicy": json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": statements,
                }
            )
        }

    def put_secret_value(self, **request: str) -> dict[str, str]:
        return {"VersionId": request["ClientRequestToken"]}


class FakeRuntimeSecret:
    def __init__(
        self,
        *,
        versions: list[dict[str, object]] | None = None,
    ) -> None:
        created_at = datetime(2026, 9, 4, 17, 0, tzinfo=UTC)
        self.created_at = created_at
        self.versions = versions or [
            {
                "VersionId": "a" * 32,
                "VersionStages": ["AWSPREVIOUS"],
                "CreatedDate": created_at - timedelta(days=1),
            },
            {
                "VersionId": "b" * 32,
                "VersionStages": ["AWSCURRENT"],
                "CreatedDate": created_at,
            },
        ]

    def describe_secret(self, *, SecretId: str) -> dict[str, object]:
        return {
            "ARN": SecretId,
            "LastChangedDate": self.created_at,
        }

    def list_secret_version_ids(self, **_request: object) -> dict[str, object]:
        return {"Versions": self.versions}


def test_qualification_secret_is_write_restricted_and_uses_derived_version() -> None:
    secret_arn = (
        "arn:aws:secretsmanager:us-east-1:123456789012:"
        "secret:ai-fde/qualification-AbCdEf"
    )
    client = FakeQualificationSecret()
    policy = json.loads(client.get_resource_policy(SecretId=secret_arn)["ResourcePolicy"])
    policy_sha256 = _canonical_policy_digest(policy)
    boundary = _verify_qualification_secret_boundary(
        client,
        secret_arn=secret_arn,
        qualifier_role_arn=QUALIFIER_ROLE_ARN,
        expected_policy_sha256=policy_sha256,
    )
    assert boundary["only_writer_role_arn"] == QUALIFIER_ROLE_ARN

    record = {"validation_id": "sha256:" + ("a" * 64)}
    assert (
        _publish_qualification_record(client, secret_id=secret_arn, record=record)
        == "a" * 64
    )

    with pytest.raises(ReadinessFailure, match="exact Terraform contract"):
        _verify_qualification_secret_boundary(
            FakeQualificationSecret(allowed_role_arn="arn:aws:iam::123456789012:role/deployer"),
            secret_arn=secret_arn,
            qualifier_role_arn=QUALIFIER_ROLE_ARN,
            expected_policy_sha256=policy_sha256,
        )

    for mutation in ("resource", "extra"):
        with pytest.raises(ReadinessFailure, match="Terraform contract"):
            _verify_qualification_secret_boundary(
                FakeQualificationSecret(mutation=mutation),
                secret_arn=secret_arn,
                qualifier_role_arn=QUALIFIER_ROLE_ARN,
                expected_policy_sha256=policy_sha256,
            )

    with pytest.raises(ReadinessFailure, match="64 KiB"):
        _publish_qualification_record(
            client,
            secret_id=secret_arn,
            record={
                "validation_id": "sha256:" + "b" * 64,
                "oversized": "x" * (64 * 1024),
            },
        )


def test_runtime_secret_requires_one_signed_current_version_bound_to_ecs() -> None:
    secret_arn = (
        "arn:aws:secretsmanager:us-east-1:123456789012:"
        "secret:ai-fde/api-AbCdEf"
    )
    migration_secret_arn = secret_arn.replace("/api-", "/migration-")
    selector_inventory = {
        "api": {
            name: f"{secret_arn}:{name}::{'b' * 32}"
            for name in {"AI_FDE_DATABASE_URL", "AI_FDE_OIDC_CLIENT_SECRET"}
        },
        "migration": {
            name: f"{migration_secret_arn}:{name}::{'b' * 32}"
            for name in {
                "AI_FDE_MIGRATION_DATABASE_URL",
                "AI_FDE_APP_DATABASE_PASSWORD",
            }
        },
    }
    now = datetime(2026, 9, 4, 18, 0, tzinfo=UTC)
    result = _verify_secret(
        FakeRuntimeSecret(),
        secret_arn,
        90,
        expected_current_version_id="b" * 32,
        now=now,
    )
    bound = _bind_runtime_secrets_to_ecs(
        {
            "api": result,
            "migration": {
                **result,
                "secret_arn": migration_secret_arn,
            },
        },
        {
            "task_definition_registered_at": {
                "api": "2026-09-04T17:30:00+00:00",
                "migration": "2026-09-04T17:30:00+00:00",
            },
            "runtime_secret_value_from": selector_inventory,
        },
    )
    assert bound["api"]["current_version_id"] == "b" * 32

    activated = {
        runtime_name: {
            **secret,
            "task_definition_registered_at": "2026-09-04T18:30:00+00:00",
        }
        for runtime_name, secret in bound.items()
    }
    _verify_runtime_secret_transition(cast(dict[str, Any], bound), activated)
    activated["api"]["ecs_value_from"] = {
        "AI_FDE_DATABASE_URL": f"{secret_arn}:AI_FDE_DATABASE_URL::{'d' * 32}",
        "AI_FDE_OIDC_CLIENT_SECRET": (
            f"{secret_arn}:AI_FDE_OIDC_CLIENT_SECRET::{'d' * 32}"
        ),
    }
    with pytest.raises(ReadinessFailure, match="version or selector"):
        _verify_runtime_secret_transition(cast(dict[str, Any], bound), activated)

    duplicate_current = FakeRuntimeSecret(
        versions=[
            {
                "VersionId": "b" * 32,
                "VersionStages": ["AWSCURRENT"],
                "CreatedDate": now - timedelta(hours=1),
            },
            {
                "VersionId": "c" * 32,
                "VersionStages": ["AWSCURRENT"],
                "CreatedDate": now - timedelta(minutes=30),
            },
        ]
    )
    with pytest.raises(ReadinessFailure, match="exactly one AWSCURRENT"):
        _verify_secret(
            duplicate_current,
            secret_arn,
            90,
            expected_current_version_id="b" * 32,
            now=now,
        )
    with pytest.raises(ReadinessFailure, match="signed rotation evidence"):
        _verify_secret(
            FakeRuntimeSecret(),
            secret_arn,
            90,
            expected_current_version_id="c" * 32,
            now=now,
        )
    with pytest.raises(ReadinessFailure, match="predates its bound AWSCURRENT"):
        _bind_runtime_secrets_to_ecs(
            {
                "api": result,
                "migration": {
                    **result,
                    "secret_arn": migration_secret_arn,
                },
            },
            {
                "task_definition_registered_at": {
                    "api": "2026-09-04T16:59:00+00:00",
                    "migration": "2026-09-04T17:30:00+00:00",
                },
                "runtime_secret_value_from": selector_inventory,
            },
        )


class FakeControlPlaneIAM:
    def __init__(
        self,
        *,
        extra_inline: bool = False,
        wrong_trust: bool = False,
        allow_qualifier_sign: bool = False,
        allow_issuer_put: bool = False,
    ) -> None:
        self.extra_inline = extra_inline
        self.wrong_trust = wrong_trust
        self.allow_qualifier_sign = allow_qualifier_sign
        self.allow_issuer_put = allow_issuer_put
        self.roles = {
            "qualifier": {
                "arn": QUALIFIER_ROLE_ARN,
                "principal": "arn:aws:iam::123456789012:role/qualification-principal",
                "policy_name": "deployment-qualification",
            },
            "deployment": {
                "arn": DEPLOYMENT_ROLE_ARN,
                "principal": "arn:aws:iam::123456789012:role/deployment-principal",
                "policy_name": "release",
            },
            "evidence_issuer": {
                "arn": EVIDENCE_ISSUER_ROLE_ARN,
                "principal": "arn:aws:iam::123456789012:role/evidence-principal",
                "policy_name": "sign-qualification-evidence",
            },
        }

    def _role(self, role_name: str) -> tuple[str, dict[str, str]]:
        for kind, value in self.roles.items():
            if value["arn"].endswith(f"/{role_name}"):
                return kind, value
        raise AssertionError(f"unexpected role {role_name}")

    def trust_policy(self, kind: str) -> dict[str, object]:
        principal = self.roles[kind]["principal"]
        if self.wrong_trust and kind == "qualifier":
            principal = "arn:aws:iam::123456789012:role/unexpected"
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": principal},
                    "Action": "sts:AssumeRole",
                }
            ],
        }

    def inline_policy(self, kind: str) -> dict[str, object]:
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": f"test:{kind}",
                    "Resource": "*",
                }
            ],
        }

    def boundary(self, secret_arn: str) -> dict[str, object]:
        return {
            "qualification_secret_arn": secret_arn,
            "signing_key_arn": EVIDENCE_SIGNING_KEY_ARN,
            "roles": {
                kind: {
                    "role_arn": role["arn"],
                    "trusted_principal_arn": role["principal"],
                    "trust_policy_sha256": _canonical_policy_digest(
                        {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Principal": {"AWS": role["principal"]},
                                    "Action": "sts:AssumeRole",
                                }
                            ],
                        }
                    ),
                    "inline_policy_sha256": {
                        role["policy_name"]: _canonical_policy_digest(
                            self.inline_policy(kind)
                        )
                    },
                }
                for kind, role in self.roles.items()
            },
        }

    def get_role(self, *, RoleName: str) -> dict[str, object]:
        kind, role = self._role(RoleName)
        return {
            "Role": {
                "Arn": role["arn"],
                "AssumeRolePolicyDocument": self.trust_policy(kind),
            }
        }

    def list_role_policies(self, *, RoleName: str, **_request: object) -> dict[str, object]:
        kind, role = self._role(RoleName)
        names = [role["policy_name"]]
        if self.extra_inline and kind == "qualifier":
            names.append("unexpected")
        return {"PolicyNames": names, "IsTruncated": False}

    def get_role_policy(
        self, *, RoleName: str, PolicyName: str
    ) -> dict[str, object]:
        kind, role = self._role(RoleName)
        assert PolicyName == role["policy_name"]
        return {"PolicyDocument": self.inline_policy(kind)}

    def list_attached_role_policies(self, **_request: object) -> dict[str, object]:
        return {"AttachedPolicies": [], "IsTruncated": False}

    def list_instance_profiles_for_role(self, **_request: object) -> dict[str, object]:
        return {"InstanceProfiles": [], "IsTruncated": False}

    def simulate_principal_policy(self, **request: object) -> dict[str, object]:
        role_arn = cast(str, request["PolicySourceArn"])
        action = cast(list[str], request["ActionNames"])[0]
        role_kind = next(
            kind for kind, role in self.roles.items() if role["arn"] == role_arn
        )
        allowed = (
            action == "kms:Sign" and role_kind == "evidence_issuer"
        ) or (
            action == "secretsmanager:PutSecretValue"
            and role_kind == "qualifier"
        )
        if self.allow_qualifier_sign and role_kind == "qualifier" and action == "kms:Sign":
            allowed = True
        if (
            self.allow_issuer_put
            and role_kind == "evidence_issuer"
            and action == "secretsmanager:PutSecretValue"
        ):
            allowed = True
        return {
            "EvaluationResults": [
                {"EvalDecision": "allowed" if allowed else "implicitDeny"}
            ]
        }


def _verify_control_plane(client: FakeControlPlaneIAM) -> dict[str, object]:
    secret_arn = (
        "arn:aws:secretsmanager:us-east-1:123456789012:"
        "secret:ai-fde/qualification-AbCdEf"
    )
    return _verify_qualification_control_plane(
        client,
        expected=cast(dict[str, Any], client.boundary(secret_arn)),
        qualifier_role_arn=QUALIFIER_ROLE_ARN,
        deployment_role_arn=DEPLOYMENT_ROLE_ARN,
        evidence_issuer_role_arn=EVIDENCE_ISSUER_ROLE_ARN,
        signing_key_arn=EVIDENCE_SIGNING_KEY_ARN,
        qualification_secret_arn=secret_arn,
    )


def test_qualification_control_plane_requires_two_party_exact_role_boundaries() -> None:
    result = _verify_control_plane(FakeControlPlaneIAM())
    assert result["status"] == "passed"

    with pytest.raises(ReadinessFailure, match="inline-policy inventory drifted"):
        _verify_control_plane(FakeControlPlaneIAM(extra_inline=True))
    with pytest.raises(ReadinessFailure, match="role trust"):
        _verify_control_plane(FakeControlPlaneIAM(wrong_trust=True))
    with pytest.raises(ReadinessFailure, match="KMS signing boundary"):
        _verify_control_plane(FakeControlPlaneIAM(allow_qualifier_sign=True))
    with pytest.raises(ReadinessFailure, match="mutation boundary"):
        _verify_control_plane(FakeControlPlaneIAM(allow_issuer_put=True))


class FakeECSDataRoleIAM:
    def __init__(self, *, mutation: str | None = None) -> None:
        self.mutation = mutation
        self.trust = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
        self.role_arns = {
            "api_task": TASK_ROLE_ARNS["api"],
            "api_execution": EXECUTION_ROLE_ARNS["api"],
            "migration_task": TASK_ROLE_ARNS["migration"],
            "migration_execution": EXECUTION_ROLE_ARNS["migration"],
        }
        self.inline_policies = {
            "api_task": {
                "evidence-objects": self._policy("api-evidence"),
            },
            "api_execution": {
                "runtime-secret": self._policy("api-secret"),
            },
            "migration_task": {
                "package-retrieval-secret-delivery": self._policy(
                    "migration-package"
                ),
            },
            "migration_execution": {
                "runtime-secret": self._policy("migration-secret"),
            },
        }

    @staticmethod
    def _policy(label: str) -> dict[str, object]:
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": f"test:{label}",
                    "Resource": "*",
                }
            ],
        }

    def _kind(self, role_name: str) -> str:
        return next(
            kind
            for kind, role_arn in self.role_arns.items()
            if role_arn.endswith(f"/{role_name}")
        )

    def boundary(self) -> dict[str, object]:
        execution_policy = (
            "arn:aws:iam::aws:policy/service-role/"
            "AmazonECSTaskExecutionRolePolicy"
        )
        return {
            "task_role_arns": TASK_ROLE_ARNS,
            "execution_role_arns": EXECUTION_ROLE_ARNS,
            "data_role_contracts": {
                kind: {
                    "role_arn": role_arn,
                    "trust_policy_sha256": _canonical_policy_digest(self.trust),
                    "inline_policy_sha256": {
                        name: _canonical_policy_digest(policy)
                        for name, policy in self.inline_policies[kind].items()
                    },
                    "attached_managed_policy_arns": (
                        [execution_policy] if kind.endswith("_execution") else []
                    ),
                }
                for kind, role_arn in self.role_arns.items()
            },
        }

    def get_role(self, *, RoleName: str) -> dict[str, object]:
        kind = self._kind(RoleName)
        trust = cast(dict[str, object], self.trust)
        if self.mutation == "trust" and kind == "api_task":
            trust = self._policy("wrong-trust")
        return {
            "Role": {
                "Arn": self.role_arns[kind],
                "AssumeRolePolicyDocument": trust,
                **(
                    {
                        "PermissionsBoundary": {
                            "PermissionsBoundaryArn": (
                                "arn:aws:iam::aws:policy/AdministratorAccess"
                            )
                        }
                    }
                    if self.mutation == "boundary" and kind == "migration_task"
                    else {}
                ),
            }
        }

    def list_role_policies(
        self, *, RoleName: str, **_request: object
    ) -> dict[str, object]:
        kind = self._kind(RoleName)
        names = list(self.inline_policies[kind])
        if self.mutation == "inline" and kind == "api_task":
            names.append("unexpected-admin")
        return {"PolicyNames": names, "IsTruncated": False}

    def get_role_policy(
        self, *, RoleName: str, PolicyName: str
    ) -> dict[str, object]:
        return {"PolicyDocument": self.inline_policies[self._kind(RoleName)][PolicyName]}

    def list_attached_role_policies(
        self, *, RoleName: str, **_request: object
    ) -> dict[str, object]:
        kind = self._kind(RoleName)
        policies = (
            [
                {
                    "PolicyArn": (
                        "arn:aws:iam::aws:policy/service-role/"
                        "AmazonECSTaskExecutionRolePolicy"
                    )
                }
            ]
            if kind.endswith("_execution")
            else []
        )
        if self.mutation == "managed" and kind == "migration_task":
            policies.append(
                {"PolicyArn": "arn:aws:iam::aws:policy/AdministratorAccess"}
            )
        return {"AttachedPolicies": policies, "IsTruncated": False}

    def list_instance_profiles_for_role(
        self, *, RoleName: str, **_request: object
    ) -> dict[str, object]:
        kind = self._kind(RoleName)
        profiles = (
            [{"Arn": "arn:aws:iam::123456789012:instance-profile/unexpected"}]
            if self.mutation == "profile" and kind == "api_task"
            else []
        )
        return {"InstanceProfiles": profiles, "IsTruncated": False}


def test_ecs_data_roles_require_exact_live_trust_and_policy_inventory() -> None:
    client = FakeECSDataRoleIAM()
    result = _verify_ecs_data_role_inventory(
        client,
        expected=cast(dict[str, Any], client.boundary()),
        task_role_arns=TASK_ROLE_ARNS,
        execution_role_arns=EXECUTION_ROLE_ARNS,
    )
    assert result["task_role_arns"] == TASK_ROLE_ARNS

    for mutation in ("trust", "inline", "managed", "boundary", "profile"):
        mutated = FakeECSDataRoleIAM(mutation=mutation)
        with pytest.raises(ReadinessFailure, match="drifted"):
            _verify_ecs_data_role_inventory(
                mutated,
                expected=cast(dict[str, Any], mutated.boundary()),
                task_role_arns=TASK_ROLE_ARNS,
                execution_role_arns=EXECUTION_ROLE_ARNS,
            )


class FakeECS:
    def __init__(self) -> None:
        self.rollback = True
        self.image_override: dict[str, str] = {}
        self.secret_arn_override: dict[str, str] = {}
        self.secret_version_override: dict[str, str] = {}
        self.sanitized_data_enabled = False
        self.qualification_secret_arn: str | None = None
        self.qualification_version_id: str | None = None
        self.extra_environment: dict[str, list[dict[str, str]]] = {}
        self.extra_secrets: dict[str, list[dict[str, str]]] = {}
        self.stale_runtime: str | None = None
        self.running_count = 1
        self.desired_count = 1
        self.pending_count = 0
        self.surplus_service_task = False
        self.stopped_runtime: str | None = None
        self.stopped_last_status = "STOPPED"
        self.stopped_prior_revision = False
        self.migration_revision = 1
        self.migration_exit_code = 0
        self.task_role_override: dict[str, str] = {}
        self.execution_role_override: dict[str, str] = {}

    def task_definition_arn(self, runtime_name: str) -> str:
        revision = self.migration_revision if runtime_name == "migration" else 1
        return (
            "arn:aws:ecs:us-east-1:123456789012:"
            f"task-definition/ai-fde-{runtime_name}:{revision}"
        )

    def describe_services(self, *, cluster: str, services: list[str]) -> dict[str, Any]:
        del cluster
        return {
            "failures": [],
            "services": [
                {
                    "serviceName": name,
                    "runningCount": self.running_count,
                    "desiredCount": self.desired_count,
                    "pendingCount": self.pending_count,
                    "taskDefinition": self.task_definition_arn(name),
                    "networkConfiguration": {
                        "awsvpcConfiguration": {
                            "assignPublicIp": "DISABLED",
                            "securityGroups": [f"sg-{name}"],
                            "subnets": ["subnet-a", "subnet-b"],
                        }
                    },
                    "deploymentConfiguration": {
                        "deploymentCircuitBreaker": {
                            "enable": True,
                            "rollback": self.rollback,
                        }
                    },
                    "deployments": [
                        {
                            "status": "PRIMARY",
                            "rolloutState": "COMPLETED",
                            "taskDefinition": self.task_definition_arn(name),
                            "runningCount": 1,
                            "pendingCount": 0,
                        }
                    ],
                }
                for name in services
            ],
        }

    def describe_task_definition(self, *, taskDefinition: str) -> dict[str, Any]:
        runtime_name = "migration" if taskDefinition == "alpha-migration" else taskDefinition
        if "task-definition/" in runtime_name:
            runtime_name = runtime_name.split("task-definition/", maxsplit=1)[1].rsplit(":", 1)[0]
            runtime_name = runtime_name.removeprefix("ai-fde-")
        image = self.image_override.get(runtime_name, IMAGES[runtime_name])
        secret_names = {
            "web": [],
            "api": ["AI_FDE_DATABASE_URL", "AI_FDE_OIDC_CLIENT_SECRET"],
            "worker": [],
            "migration": [
                "AI_FDE_MIGRATION_DATABASE_URL",
                "AI_FDE_APP_DATABASE_PASSWORD",
            ],
        }[runtime_name]
        python_environment = (
            []
            if runtime_name == "web"
            else [
                {"name": "AI_FDE_ENV", "value": "production"},
                {"name": "AI_FDE_AUTH_MODE", "value": "oidc"},
                {"name": "AI_FDE_ALLOWED_ORIGINS", "value": '["https://ai-fde.example"]'},
                {"name": "AI_FDE_COCKPIT_URL", "value": "https://ai-fde.example"},
                {"name": "AI_FDE_OIDC_ISSUER_URL", "value": "https://tenant.example/"},
                {"name": "AI_FDE_OIDC_CLIENT_ID", "value": "design-partner-client"},
                {
                    "name": "AI_FDE_OIDC_REDIRECT_URI",
                    "value": "https://ai-fde.example/api/auth/callback",
                },
                {"name": "AI_FDE_OIDC_ALLOWED_EMAILS", "value": '["operator@example.com"]'},
                {"name": "AI_FDE_BEDROCK_MODEL_ID", "value": "profile-v1"},
                {"name": "AI_FDE_BEDROCK_REGION", "value": "us-east-1"},
                {
                    "name": "AI_FDE_BEDROCK_ALLOWED_DATA_CLASSIFICATIONS",
                    "value": '["INTERNAL","PUBLIC"]',
                },
                {"name": "AI_FDE_WORKER_OPERATOR_ID", "value": WORKER_OPERATOR_ID},
                {"name": "AI_FDE_S3_BUCKET", "value": "ai-fde-evidence"},
                {"name": "AI_FDE_S3_KMS_KEY_ARN", "value": EVIDENCE_KMS_KEY_ARN},
                {"name": "AI_FDE_S3_REGION", "value": "us-east-1"},
                {"name": "AI_FDE_S3_USE_WORKLOAD_IDENTITY", "value": "true"},
                {"name": "AI_FDE_EXTRACTION_PROVIDER", "value": "bedrock"},
                {"name": "AI_FDE_WORKER_LEASE_SECONDS", "value": "300"},
                {
                    "name": "AI_FDE_SANITIZED_DATA_ENABLED",
                    "value": str(self.sanitized_data_enabled).lower(),
                },
                {
                    "name": "AI_FDE_DEPLOYMENT_QUALIFICATION_ROLE_ARN",
                    "value": QUALIFIER_ROLE_ARN,
                },
                {
                    "name": "AI_FDE_QUALIFICATION_SECRET_POLICY_SHA256",
                    "value": "sha256:" + "7" * 64,
                },
                {"name": "AI_FDE_RDS_CA_BUNDLE_PATH", "value": RDS_CA_BUNDLE_PATH},
                {"name": "AI_FDE_RDS_CA_BUNDLE_SHA256", "value": RDS_CA_BUNDLE_SHA256},
                {
                    "name": "AI_FDE_EVIDENCE_SIGNING_PUBLIC_KEY_DER_B64",
                    "value": "test-public-key",
                },
                {
                    "name": "AI_FDE_EVIDENCE_SIGNING_PUBLIC_KEY_B64_SHA256",
                    "value": "sha256:" + "0" * 64,
                },
                {"name": "AI_FDE_RUNTIME_ROLE", "value": runtime_name},
            ]
        )
        worker_boundary_environment = (
            [{"name": "AI_FDE_WORKER_ENGAGEMENT_ID", "value": WORKER_ENGAGEMENT_ID}]
            if runtime_name in {"api", "worker", "migration"}
            else []
        )
        qualification_environment = (
            [
                {
                    "name": "AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD_VERSION_ID",
                    "value": self.qualification_version_id,
                }
            ]
            if runtime_name != "web" and self.qualification_version_id is not None
            else []
        )
        qualification_secret = (
            [
                {
                    "name": "AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD",
                    "valueFrom": (
                        f"{self.qualification_secret_arn}:::{self.qualification_version_id}"
                    ),
                }
            ]
            if runtime_name != "web"
            and self.qualification_secret_arn is not None
            and self.qualification_version_id is not None
            else []
        )
        return {
            "taskDefinition": {
                "taskDefinitionArn": self.task_definition_arn(runtime_name),
                "registeredAt": datetime(2026, 9, 4, 19, 0, tzinfo=UTC),
                "requiresCompatibilities": ["FARGATE"],
                "networkMode": "awsvpc",
                "taskRoleArn": self.task_role_override.get(
                    runtime_name, TASK_ROLE_ARNS[runtime_name]
                ),
                "executionRoleArn": self.execution_role_override.get(
                    runtime_name, EXECUTION_ROLE_ARNS[runtime_name]
                ),
                "containerDefinitions": [
                    {
                        "name": runtime_name,
                        "image": image,
                        "versionConsistency": "enabled",
                        "environment": (
                            [
                                {"name": "NODE_ENV", "value": "production"},
                                {"name": "HOSTNAME", "value": "0.0.0.0"},
                                {"name": "PORT", "value": "3000"},
                            ]
                            if runtime_name == "web"
                            else []
                        ) + [
                            {"name": "AI_FDE_RELEASE_REVISION", "value": "a" * 40},
                            {
                                "name": "AI_FDE_DEPLOYMENT_ID",
                                "value": "deploy-2026-09-04-a",
                            },
                            {
                                "name": "AI_FDE_DEPLOYMENT_QUALIFICATION_MODE",
                                "value": "controlled-design-partner",
                            },
                        ]
                        + python_environment
                        + worker_boundary_environment
                        + qualification_environment
                        + (
                            [
                                {
                                    "name": "AI_FDE_DATABASE_URL",
                                    "value": WORKER_DATABASE_URL,
                                },
                                {
                                    "name": "AI_FDE_DATABASE_AUTH_MODE",
                                    "value": "rds-iam",
                                },
                            ]
                            if runtime_name == "worker"
                            else []
                        ) + self.extra_environment.get(runtime_name, []),
                        "secrets": [
                            {
                                "name": name,
                                "valueFrom": (
                                    self.secret_arn_override.get(
                                        runtime_name, SECRET_ARNS[runtime_name]
                                    )
                                    + f":{name}::"
                                    + self.secret_version_override.get(
                                        runtime_name,
                                        SECRET_VERSION_IDS[runtime_name],
                                    )
                                ),
                            }
                            for name in secret_names
                        ]
                        + qualification_secret
                        + self.extra_secrets.get(runtime_name, []),
                    }
                ],
            }
        }

    def list_tasks(self, **request: Any) -> dict[str, object]:
        if request["desiredStatus"] == "STOPPED":
            service = request.get("serviceName")
            if self.stopped_runtime is None or (
                service is not None
                and (
                    self.stopped_runtime not in {"web", "api", "worker"}
                    or service != self.stopped_runtime
                )
            ):
                return {"taskArns": []}
            return {
                "taskArns": [
                    "arn:aws:ecs:us-east-1:123456789012:task/"
                    f"ai-fde-design-partner/{self.stopped_runtime}-stopped"
                ]
            }
        assert request["desiredStatus"] == "RUNNING"
        service = request.get("serviceName")
        runtime_names = [str(service)] if service is not None else ["web", "api", "worker"]
        task_arns = [
            "arn:aws:ecs:us-east-1:123456789012:task/"
            f"ai-fde-design-partner/{runtime_name}-current"
            for runtime_name in runtime_names
        ]
        if service is None and self.stale_runtime is not None:
            task_arns.append(
                "arn:aws:ecs:us-east-1:123456789012:task/"
                f"ai-fde-design-partner/{self.stale_runtime}-stale"
            )
        if self.surplus_service_task and (service is None or service == "worker"):
            task_arns.append(
                "arn:aws:ecs:us-east-1:123456789012:task/"
                "ai-fde-design-partner/worker-surplus"
            )
        return {"taskArns": task_arns}

    def describe_tasks(self, *, cluster: str, tasks: list[str]) -> dict[str, object]:
        del cluster
        described: list[dict[str, object]] = []
        for task_arn in tasks:
            task_name = task_arn.rsplit("/", maxsplit=1)[-1]
            runtime_name = task_name.split("-", maxsplit=1)[0]
            is_stopped = task_name.endswith("-stopped")
            desired_status = "STOPPED" if is_stopped else "RUNNING"
            last_status = self.stopped_last_status if is_stopped else "RUNNING"
            task_definition_arn = self.task_definition_arn(runtime_name)
            if is_stopped and self.stopped_prior_revision:
                task_definition_arn = task_definition_arn.rsplit(":", maxsplit=1)[0] + ":0"
            group = (
                f"family:ai-fde-{runtime_name}"
                if is_stopped and runtime_name in {"migration", "other"}
                else f"service:{runtime_name}"
            )
            described.append(
                {
                    "taskArn": task_arn,
                    # A standalone RunTask caller can choose a service-looking group;
                    # the verifier must compare ECS service inventory, not trust this field.
                    "group": group,
                    "taskDefinitionArn": task_definition_arn,
                    "desiredStatus": desired_status,
                    "lastStatus": last_status,
                    "healthStatus": "HEALTHY" if not is_stopped else "UNKNOWN",
                    "containers": [
                        {
                            "name": runtime_name,
                            "lastStatus": last_status,
                            "healthStatus": "HEALTHY" if not is_stopped else "UNKNOWN",
                            **(
                                {"exitCode": self.migration_exit_code}
                                if is_stopped and runtime_name == "migration"
                                else {}
                            ),
                        }
                    ],
                    **(
                        {
                            "stoppedAt": datetime(2026, 9, 4, 19, 0, tzinfo=UTC),
                            "stopCode": "EssentialContainerExited",
                        }
                        if is_stopped
                        else {}
                    ),
                }
            )
        return {"failures": [], "tasks": described}


class FakeBedrock:
    def __init__(self, *, status: str = "Completed", model: str = "profile-v1") -> None:
        self.status = status
        self.model = model

    def get_evaluation_job(self, *, jobIdentifier: str) -> dict[str, Any]:
        return {
            "jobArn": f"arn:aws:bedrock:us-east-1:123:evaluation-job/{jobIdentifier}",
            "jobName": jobIdentifier,
            "status": self.status,
            "applicationType": "ModelEvaluation",
            "inferenceConfig": {"models": [{"bedrockModel": {"modelIdentifier": self.model}}]},
        }


def _evidence_bucket_policy(
    *,
    kms_key_arn: str = EVIDENCE_KMS_KEY_ARN,
) -> dict[str, object]:
    bucket_arn = EVIDENCE_BUCKET_ARN
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyInsecureTransport",
                "Effect": "Deny",
                "Principal": {"AWS": "*"},
                "Action": "s3:*",
                "Resource": [bucket_arn, f"{bucket_arn}/*"],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            },
            {
                "Sid": "DenyMissingSSEKMS",
                "Effect": "Deny",
                "Principal": {"AWS": "*"},
                "Action": "s3:PutObject",
                "Resource": f"{bucket_arn}/*",
                "Condition": {
                    "Null": {
                        "s3:x-amz-server-side-encryption-aws-kms-key-id": "true"
                    }
                },
            },
            {
                "Sid": "DenyWrongSSEAlgorithm",
                "Effect": "Deny",
                "Principal": {"AWS": "*"},
                "Action": "s3:PutObject",
                "Resource": f"{bucket_arn}/*",
                "Condition": {
                    "StringNotEquals": {
                        "s3:x-amz-server-side-encryption": "aws:kms"
                    }
                },
            },
            {
                "Sid": "DenyWrongKMSKey",
                "Effect": "Deny",
                "Principal": {"AWS": "*"},
                "Action": "s3:PutObject",
                "Resource": f"{bucket_arn}/*",
                "Condition": {
                    "StringNotEquals": {
                        "s3:x-amz-server-side-encryption-aws-kms-key-id": (
                            kms_key_arn
                        )
                    }
                },
            },
        ],
    }


def _policy_sha256(policy: dict[str, object]) -> str:
    encoded = json.dumps(policy, separators=(",", ":"), sort_keys=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class FakeS3:
    def __init__(
        self,
        *,
        versioning: str = "Enabled",
        retention_days: int = 30,
        policy: dict[str, object] | None = None,
    ) -> None:
        self.versioning = versioning
        self.retention_days = retention_days
        self.policy = policy or _evidence_bucket_policy()

    def get_public_access_block(self, *, Bucket: str) -> dict[str, Any]:
        del Bucket
        return {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        }

    def get_bucket_encryption(self, *, Bucket: str) -> dict[str, Any]:
        del Bucket
        return {
            "ServerSideEncryptionConfiguration": {
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "aws:kms",
                            "KMSMasterKeyID": EVIDENCE_KMS_KEY_ARN,
                        }
                    }
                ]
            }
        }

    def get_bucket_policy(self, *, Bucket: str) -> dict[str, str]:
        del Bucket
        return {
            "Policy": json.dumps(
                self.policy,
                separators=(",", ":"),
                sort_keys=True,
            )
        }

    def get_bucket_versioning(self, *, Bucket: str) -> dict[str, Any]:
        del Bucket
        return {"Status": self.versioning}

    def get_bucket_lifecycle_configuration(self, *, Bucket: str) -> dict[str, Any]:
        del Bucket
        return {
            "Rules": [
                {
                    "Status": "Enabled",
                    "NoncurrentVersionExpiration": {
                        "NoncurrentDays": self.retention_days,
                    },
                }
            ]
        }


class FakeIAM:
    def __init__(
        self,
        *,
        allow_cross_engagement: bool = False,
        allow_worker_mutation: bool = False,
        allow_bucket_enumeration: bool = False,
        allow_direct_kms: bool = False,
        allow_alternate_model: bool = False,
        allow_non_worker_rds: bool = False,
        allow_prior_current_resources: bool = False,
        get_role_error: str | None = None,
        quarantine_mutation: str | None = None,
    ) -> None:
        self.allow_cross_engagement = allow_cross_engagement
        self.allow_worker_mutation = allow_worker_mutation
        self.allow_bucket_enumeration = allow_bucket_enumeration
        self.allow_direct_kms = allow_direct_kms
        self.allow_alternate_model = allow_alternate_model
        self.allow_non_worker_rds = allow_non_worker_rds
        self.allow_prior_current_resources = allow_prior_current_resources
        self.get_role_error = get_role_error
        self.quarantine_mutation = quarantine_mutation

    def get_role(self, *, RoleName: str) -> dict[str, object]:
        if self.get_role_error is not None:
            raise ClientError(
                {"Error": {"Code": self.get_role_error, "Message": "test"}},
                "GetRole",
            )
        return {
            "Role": {
                "RoleName": RoleName,
                "Arn": PRIOR_WORKER_TASK_ROLE_ARN,
                "MaxSessionDuration": 3600,
                "AssumeRolePolicyDocument": (
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"AWS": "*"},
                                "Action": "sts:AssumeRole",
                            }
                        ],
                    }
                    if self.quarantine_mutation == "trust"
                    else {
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
                ),
                **(
                    {
                        "PermissionsBoundary": {
                            "PermissionsBoundaryType": "Policy",
                            "PermissionsBoundaryArn": "arn:aws:iam::aws:policy/ReadOnlyAccess",
                        }
                    }
                    if self.quarantine_mutation == "boundary"
                    else {}
                ),
            }
        }

    def list_attached_role_policies(self, **_request: object) -> dict[str, object]:
        return {
            "AttachedPolicies": (
                [{"PolicyArn": "arn:aws:iam::aws:policy/ReadOnlyAccess"}]
                if self.quarantine_mutation == "managed"
                else []
            ),
            "IsTruncated": False,
        }

    def list_instance_profiles_for_role(self, **_request: object) -> dict[str, object]:
        return {
            "InstanceProfiles": (
                [{"InstanceProfileName": "unexpected"}]
                if self.quarantine_mutation == "profile"
                else []
            ),
            "IsTruncated": False,
        }

    def list_role_policies(self, **_request: object) -> dict[str, object]:
        policy_names = ["AWSRevokeOlderSessions"]
        if self.quarantine_mutation == "inline":
            policy_names.append("RestoredGrant")
        return {"PolicyNames": policy_names, "IsTruncated": False}

    def get_role_policy(self, **_request: object) -> dict[str, object]:
        cutoff = datetime(2026, 9, 4, 18, 0, tzinfo=UTC)
        if self.quarantine_mutation == "cutoff":
            cutoff += timedelta(minutes=1)
        return {"PolicyDocument": _test_quarantine_policy(cutoff)}

    def simulate_principal_policy(self, **request: Any) -> dict[str, Any]:
        action = request["ActionNames"][0]
        resource = request["ResourceArns"][0]
        context = request.get("ContextEntries", [])
        current_worker = request["PolicySourceArn"].endswith("/worker-task")
        prior_worker = request["PolicySourceArn"] == PRIOR_WORKER_TASK_ROLE_ARN
        own_prefix = f"{EVIDENCE_BUCKET_ARN}/engagements/{WORKER_ENGAGEMENT_ID}/"
        allowed = action in {"s3:GetObject", "s3:GetObjectVersion"} and current_worker and (
            resource.startswith(own_prefix) or self.allow_cross_engagement
        )
        if action in {"s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"}:
            allowed = current_worker and self.allow_worker_mutation
        if action in {"s3:ListBucket", "s3:GetBucketLocation"}:
            allowed = self.allow_bucket_enumeration
        if action == "kms:Decrypt":
            allowed = current_worker and (self.allow_direct_kms or context == [
                {
                    "ContextKeyName": "kms:ViaService",
                    "ContextKeyValues": ["s3.us-east-1.amazonaws.com"],
                    "ContextKeyType": "string",
                },
                {
                    "ContextKeyName": "kms:EncryptionContext:aws:s3:arn",
                    "ContextKeyValues": [EVIDENCE_BUCKET_ARN],
                    "ContextKeyType": "string",
                },
            ])
        if action == "bedrock:InvokeModel":
            allowed = current_worker and (
                resource == BEDROCK_MODEL_ARN or self.allow_alternate_model
            )
        if action == "rds-db:connect":
            allowed = current_worker or self.allow_non_worker_rds
        if prior_worker and self.allow_prior_current_resources:
            allowed = True
        return {"EvaluationResults": [{"EvalDecision": "allowed" if allowed else "implicitDeny"}]}


class FakeRDS:
    def __init__(
        self,
        latest_restorable_time: datetime,
        *,
        mutation: str | None = None,
    ) -> None:
        self.latest_restorable_time = latest_restorable_time
        self.mutation = mutation

    def describe_db_instances(self, *, DBInstanceIdentifier: str) -> dict[str, Any]:
        database: dict[str, Any] = {
            "DBInstanceIdentifier": DBInstanceIdentifier,
            "DBInstanceStatus": "available",
            "Engine": "postgres",
            "PubliclyAccessible": False,
            "StorageEncrypted": True,
            "MultiAZ": True,
            "IAMDatabaseAuthenticationEnabled": True,
            "DbiResourceId": "db-ABCDEFGHIJKLMNOPQRSTUVWXY",
            "KmsKeyId": EVIDENCE_KMS_KEY_ARN,
            "DBSubnetGroup": {
                "VpcId": "vpc-11111111",
                "Subnets": [
                    {
                        "SubnetIdentifier": "subnet-11111111",
                        "SubnetStatus": "Active",
                    },
                    {
                        "SubnetIdentifier": "subnet-22222222",
                        "SubnetStatus": "Active",
                    },
                ],
            },
            "VpcSecurityGroups": [
                {"VpcSecurityGroupId": "sg-33333333", "Status": "active"}
            ],
            "Endpoint": {
                "Address": "db.example.us-east-1.rds.amazonaws.com",
                "Port": 5432,
            },
            "DBName": "ai_fde",
            "BackupRetentionPeriod": 7,
            "DeletionProtection": True,
            "LatestRestorableTime": self.latest_restorable_time,
            "DBParameterGroups": [{"DBParameterGroupName": "postgres16"}],
        }
        if self.mutation == "public":
            database["PubliclyAccessible"] = True
        elif self.mutation == "kms":
            database["KmsKeyId"] = EVIDENCE_SIGNING_KEY_ARN
        elif self.mutation == "subnet":
            cast(dict[str, Any], database["DBSubnetGroup"])["Subnets"] = [
                {
                    "SubnetIdentifier": "subnet-99999999",
                    "SubnetStatus": "Active",
                }
            ]
        return {
            "DBInstances": [
                database
            ]
        }

    def describe_db_parameters(
        self, *, DBParameterGroupName: str, Filters: list[dict[str, object]]
    ) -> dict[str, Any]:
        del DBParameterGroupName, Filters
        return {"Parameters": [{"ParameterValue": "1"}]}


def _image(name: str) -> str:
    digest_character = {"web": "b", "api": "a", "worker": "c", "wrong": "d"}[name]
    return f"123.dkr.ecr.us-east-1.amazonaws.com/{name}@sha256:" + (digest_character * 64)


IMAGES = {
    "web": _image("web"),
    "api": _image("api"),
    "worker": _image("worker"),
    "migration": _image("api"),
}

SECRET_ARNS = {
    "api": "arn:aws:secretsmanager:us-east-1:123456789012:secret:ai-fde/api-AbCdEf",
    "worker": "arn:aws:secretsmanager:us-east-1:123456789012:secret:ai-fde/worker-AbCdEf",
    "migration": "arn:aws:secretsmanager:us-east-1:123456789012:secret:ai-fde/migration-AbCdEf",
}


def test_release_inputs_require_exact_commit_digests_and_deployment_identity() -> None:
    args = Namespace(
        application_url="https://ai-fde.example",
        region="us-east-1",
        git_commit="a" * 40,
        deployment_id="deploy-2026-09-04-a",
        qualification_mode="controlled-design-partner",
        worker_engagement_id=WORKER_ENGAGEMENT_ID,
        worker_operator_id=WORKER_OPERATOR_ID,
        qualification_validity_hours=24,
        max_external_evidence_age_days=30,
        max_rpo_minutes=15,
        max_secret_age_days=90,
        bedrock_allowed_data_classification=None,
        web_image=IMAGES["web"],
        api_image=IMAGES["api"],
        worker_image=IMAGES["worker"],
        bedrock_model_id="profile-v1",
        bedrock_model_arn=BEDROCK_MODEL_ARN,
        evidence_issuer_role_arn=EVIDENCE_ISSUER_ROLE_ARN,
        evidence_signing_key_arn=EVIDENCE_SIGNING_KEY_ARN,
        worker_task_role_arn=WORKER_TASK_ROLE_ARN,
        prior_worker_task_role_arn=[PRIOR_WORKER_TASK_ROLE_ARN],
            no_prior_worker_task_roles=False,
            oidc_issuer_url="https://tenant.example/",
            oidc_client_id="design-partner-client",
            oidc_allowed_email=["operator@example.com"],
    )
    assert _release_inputs(args)["git_commit"] == "a" * 40

    args.git_commit = "main"
    with pytest.raises(ReadinessFailure, match="40-character"):
        _release_inputs(args)
    args.git_commit = "a" * 40
    args.web_image = "example/web:latest"
    with pytest.raises(ReadinessFailure, match="pinned"):
        _release_inputs(args)
    args.web_image = IMAGES["web"]
    args.deployment_id = "pending"
    with pytest.raises(ReadinessFailure, match="deployment ID"):
        _release_inputs(args)

    args.deployment_id = "deploy-2026-09-04-a"
    args.bedrock_allowed_data_classification = ["RESTRICTED"]
    with pytest.raises(ReadinessFailure, match="RESTRICTED"):
        _release_inputs(args)

    args.bedrock_allowed_data_classification = None
    args.worker_engagement_id = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(ReadinessFailure, match="nonzero canonical"):
        _release_inputs(args)

    args.worker_engagement_id = WORKER_ENGAGEMENT_ID
    args.bedrock_model_arn = "*"
    with pytest.raises(ReadinessFailure, match="foundation-model ARN"):
        _release_inputs(args)

    args.bedrock_model_arn = BEDROCK_MODEL_ARN
    args.bedrock_model_id = "profile-v2"
    with pytest.raises(ReadinessFailure, match="does not match"):
        _release_inputs(args)


def test_public_health_endpoint_must_be_credential_free_https() -> None:
    with pytest.raises(ReadinessFailure, match="credential-free HTTPS"):
        _verify_https(
            "http://ai-fde.example/api/ready",
            expected_release_revision="a" * 40,
            expected_deployment_id="deploy-2026-09-04-a",
            expected_qualification_mode="controlled-design-partner",
        )


def test_public_readiness_response_is_bound_to_the_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "status": "ready",
        "release_revision": "a" * 40,
        "deployment_id": "deploy-2026-09-04-a",
        "qualification_mode": "controlled-design-partner",
        "sanitized_data_enabled": False,
        "deployment_validation_id": None,
        "deployment_qualification_record_version_id": None,
        "deployment_qualification_content_digest": None,
        "dependencies": {
            "database": {
                "status": "ready",
                "tls_ca_path": RDS_CA_BUNDLE_PATH,
                "tls_ca_sha256": RDS_CA_BUNDLE_SHA256,
                "observed_tls_ca_sha256": RDS_CA_BUNDLE_SHA256,
            }
        },
    }
    response = MagicMock()
    response.status = 200
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    monkeypatch.setattr(
        "scripts.verify_design_partner_readiness.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    result = _verify_https(
        "https://ai-fde.example/api/ready",
        expected_release_revision="a" * 40,
        expected_deployment_id="deploy-2026-09-04-a",
        expected_qualification_mode="controlled-design-partner",
    )
    assert result["status"] == "passed"

    payload["deployment_id"] = "different-deployment"
    response.read.return_value = json.dumps(payload).encode()
    with pytest.raises(ReadinessFailure, match="deployment_id"):
        _verify_https(
            "https://ai-fde.example/api/ready",
            expected_release_revision="a" * 40,
            expected_deployment_id="deploy-2026-09-04-a",
            expected_qualification_mode="controlled-design-partner",
        )
    with pytest.raises(ReadinessFailure, match="credential-free HTTPS"):
        _verify_https(
            "https://operator:secret@ai-fde.example/api/ready",
            expected_release_revision="a" * 40,
            expected_deployment_id="deploy-2026-09-04-a",
            expected_qualification_mode="controlled-design-partner",
        )


def test_ecs_requires_release_images_rollback_and_version_consistency() -> None:
    client = FakeECS()
    result = _verify_ecs(
        client,
        cluster="alpha",
        services=["web", "api", "worker"],
        expected_migration_task_definition_arn=MIGRATION_TASK_DEFINITION_ARN,
        expected_images=IMAGES,
        expected_release_revision="a" * 40,
        expected_deployment_id="deploy-2026-09-04-a",
        expected_qualification_mode="controlled-design-partner",
        expected_bedrock_model_id="profile-v1",
        expected_bedrock_classifications=["INTERNAL", "PUBLIC"],
        expected_secret_arns=SECRET_ARNS,
        expected_secret_version_ids=SECRET_VERSION_IDS,
        expected_task_role_arns=TASK_ROLE_ARNS,
        expected_execution_role_arns=EXECUTION_ROLE_ARNS,
        expected_worker_engagement_id=WORKER_ENGAGEMENT_ID,
    )
    assert result["images"] == IMAGES
    assert result["deployment_rollback"] == "enabled"

    with pytest.raises(ReadinessFailure, match="Terraform expected"):
        _verify_ecs(
            client,
            cluster="alpha",
            services=["web", "api", "worker"],
            expected_migration_task_definition_arn=(
                MIGRATION_TASK_DEFINITION_ARN.rsplit(":", maxsplit=1)[0] + ":2"
            ),
            expected_images=IMAGES,
            expected_release_revision="a" * 40,
            expected_deployment_id="deploy-2026-09-04-a",
            expected_qualification_mode="controlled-design-partner",
            expected_bedrock_model_id="profile-v1",
            expected_bedrock_classifications=["INTERNAL", "PUBLIC"],
            expected_secret_arns=SECRET_ARNS,
            expected_secret_version_ids=SECRET_VERSION_IDS,
            expected_task_role_arns=TASK_ROLE_ARNS,
            expected_execution_role_arns=EXECUTION_ROLE_ARNS,
            expected_worker_engagement_id=WORKER_ENGAGEMENT_ID,
        )

    client.rollback = False
    with pytest.raises(ReadinessFailure, match="deployment rollback"):
        _verify_ecs(
            client,
            cluster="alpha",
            services=["web", "api", "worker"],
            expected_migration_task_definition_arn=MIGRATION_TASK_DEFINITION_ARN,
            expected_images=IMAGES,
            expected_release_revision="a" * 40,
            expected_deployment_id="deploy-2026-09-04-a",
            expected_qualification_mode="controlled-design-partner",
            expected_bedrock_model_id="profile-v1",
            expected_bedrock_classifications=["INTERNAL", "PUBLIC"],
            expected_secret_arns=SECRET_ARNS,
            expected_secret_version_ids=SECRET_VERSION_IDS,
            expected_task_role_arns=TASK_ROLE_ARNS,
            expected_execution_role_arns=EXECUTION_ROLE_ARNS,
            expected_worker_engagement_id=WORKER_ENGAGEMENT_ID,
        )
    client.rollback = True
    client.image_override["worker"] = _image("wrong")
    with pytest.raises(ReadinessFailure, match="release-bound image"):
        _verify_ecs(
            client,
            cluster="alpha",
            services=["web", "api", "worker"],
            expected_migration_task_definition_arn=MIGRATION_TASK_DEFINITION_ARN,
            expected_images=IMAGES,
            expected_release_revision="a" * 40,
            expected_deployment_id="deploy-2026-09-04-a",
            expected_qualification_mode="controlled-design-partner",
            expected_bedrock_model_id="profile-v1",
            expected_bedrock_classifications=["INTERNAL", "PUBLIC"],
            expected_secret_arns=SECRET_ARNS,
            expected_secret_version_ids=SECRET_VERSION_IDS,
            expected_task_role_arns=TASK_ROLE_ARNS,
            expected_execution_role_arns=EXECUTION_ROLE_ARNS,
            expected_worker_engagement_id=WORKER_ENGAGEMENT_ID,
        )

    client.image_override.clear()
    client.secret_arn_override["api"] = SECRET_ARNS["migration"]
    with pytest.raises(ReadinessFailure, match="exact verified secret versions"):
        _verify_ecs(
            client,
            cluster="alpha",
            services=["web", "api", "worker"],
            expected_migration_task_definition_arn=MIGRATION_TASK_DEFINITION_ARN,
            expected_images=IMAGES,
            expected_release_revision="a" * 40,
            expected_deployment_id="deploy-2026-09-04-a",
            expected_qualification_mode="controlled-design-partner",
            expected_bedrock_model_id="profile-v1",
            expected_bedrock_classifications=["INTERNAL", "PUBLIC"],
            expected_secret_arns=SECRET_ARNS,
            expected_secret_version_ids=SECRET_VERSION_IDS,
            expected_task_role_arns=TASK_ROLE_ARNS,
            expected_execution_role_arns=EXECUTION_ROLE_ARNS,
            expected_worker_engagement_id=WORKER_ENGAGEMENT_ID,
        )

    client.secret_arn_override.clear()
    client.secret_version_override["api"] = "d" * 32
    with pytest.raises(ReadinessFailure, match="exact verified secret versions"):
        _verify_fake_ecs(client)


def _verify_fake_ecs(client: FakeECS) -> dict[str, object]:
    return _verify_ecs(
        client,
        cluster="ai-fde-design-partner",
        services=["web", "api", "worker"],
        expected_migration_task_definition_arn=client.task_definition_arn("migration"),
        expected_images=IMAGES,
        expected_release_revision="a" * 40,
        expected_deployment_id="deploy-2026-09-04-a",
        expected_qualification_mode="controlled-design-partner",
        expected_bedrock_model_id="profile-v1",
        expected_bedrock_classifications=["INTERNAL", "PUBLIC"],
        expected_secret_arns=SECRET_ARNS,
        expected_secret_version_ids=SECRET_VERSION_IDS,
        expected_task_role_arns=TASK_ROLE_ARNS,
        expected_execution_role_arns=EXECUTION_ROLE_ARNS,
        expected_worker_engagement_id=WORKER_ENGAGEMENT_ID,
    )


@pytest.mark.parametrize("runtime_name", ["web", "api", "worker", "migration"])
@pytest.mark.parametrize("role_kind", ["task", "execution"])
def test_ecs_rejects_exact_runtime_with_swapped_workload_role(
    runtime_name: str,
    role_kind: str,
) -> None:
    client = FakeECS()
    swapped_role = (
        f"arn:aws:iam::123456789012:role/swapped-{runtime_name}-{role_kind}"
    )
    if role_kind == "task":
        client.task_role_override[runtime_name] = swapped_role
    else:
        client.execution_role_override[runtime_name] = swapped_role

    with pytest.raises(ReadinessFailure, match="exact Terraform task and execution roles"):
        _verify_fake_ecs(client)


def test_activation_holds_roles_exact_across_task_definition_revision_change() -> None:
    candidate = _verify_fake_ecs(FakeECS())
    activated_client = FakeECS()
    activated_client.migration_revision = 2
    activation = _verify_fake_ecs(activated_client)

    _verify_ecs_role_transition(cast(dict[str, Any], candidate), activation)

    swapped = cast(dict[str, object], dict(activation))
    swapped_roles = dict(cast(dict[str, str], activation["execution_role_arns"]))
    swapped_roles["api"] = "arn:aws:iam::123456789012:role/swapped-api-execution"
    swapped["execution_role_arns"] = swapped_roles
    with pytest.raises(ReadinessFailure, match="execution_role_arns differs"):
        _verify_ecs_role_transition(cast(dict[str, Any], candidate), swapped)


def test_ecs_rejects_duplicate_shadowed_and_unexpected_runtime_bindings() -> None:
    duplicate_environment = FakeECS()
    duplicate_environment.extra_environment["worker"] = [
        {"name": "AI_FDE_ENV", "value": "production"}
    ]
    with pytest.raises(ReadinessFailure, match="duplicate environment"):
        _verify_fake_ecs(duplicate_environment)

    duplicate_secret = FakeECS()
    duplicate_secret.extra_secrets["api"] = [
        {"name": "AI_FDE_DATABASE_URL", "valueFrom": SECRET_ARNS["api"] + ":other::"}
    ]
    with pytest.raises(ReadinessFailure, match="duplicate secrets"):
        _verify_fake_ecs(duplicate_secret)

    shadowed_secret = FakeECS()
    shadowed_secret.extra_environment["api"] = [
        {"name": "AI_FDE_DATABASE_URL", "value": "plaintext-shadow"}
    ]
    with pytest.raises(ReadinessFailure, match="shadows a secret"):
        _verify_fake_ecs(shadowed_secret)

    unexpected_environment = FakeECS()
    unexpected_environment.extra_environment["worker"] = [
        {"name": "UNEXPECTED_RUNTIME_SETTING", "value": "true"}
    ]
    with pytest.raises(ReadinessFailure, match="exact approved environment allowlist"):
        _verify_fake_ecs(unexpected_environment)


def _revocation_evidence(
    db_user_arn: str,
    *,
    identity_state: str = "retained-quarantined",
    include_role: bool = True,
) -> dict[str, object]:
    cutoff = datetime(2026, 9, 4, 18, 0, tzinfo=UTC)
    quarantine_policy_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            _test_quarantine_policy(cutoff),
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    roles: list[dict[str, object]] = []
    if include_role:
        roles.append(
            {
                "role_arn": PRIOR_WORKER_TASK_ROLE_ARN,
                "prior_release_revision": PRIOR_RELEASE_REVISION,
                "prior_deployment_id": PRIOR_DEPLOYMENT_ID,
                "identity_state": identity_state,
                "quarantine_policy_digest": quarantine_policy_digest,
                "max_session_duration_seconds": 3600,
                "revocation_cutoff_at": cutoff.isoformat(),
                "live_probe_completed_at": (
                    cutoff + timedelta(seconds=60)
                ).isoformat(),
                "deleted_at": (
                    cutoff + timedelta(hours=13)
                ).isoformat()
                if identity_state == "deleted-after-ttl"
                else None,
                "targets": {
                    "db_user_arn": db_user_arn,
                    "s3_object_prefix_arn": (
                        f"{EVIDENCE_BUCKET_ARN}/engagements/"
                        f"{WORKER_ENGAGEMENT_ID}/evidence/*"
                    ),
                    "kms_key_arn": EVIDENCE_KMS_KEY_ARN,
                    "bedrock_model_arn": BEDROCK_MODEL_ARN,
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
        )
    return {
        "content_digest": "sha256:" + "a" * 64,
        "signed_record": {
            "release_revision": "a" * 40,
            "deployment_id": "deploy-2026-09-04-a",
            "results": {"roles": roles},
        },
    }


def test_candidate_drains_standalone_tasks_and_denies_every_prior_worker_role() -> None:
    ecs = FakeECS()
    ecs_check = _verify_fake_ecs(ecs)
    task_definitions = ecs_check["task_definition_arns"]
    assert isinstance(task_definitions, dict)
    drain = _verify_standalone_task_drain(
        ecs,
        cluster="ai-fde-design-partner",
        task_definition_arns=task_definitions,
        services={"web": "web", "api": "api", "worker": "worker", "migration": None},
        service_desired_counts={"web": 1, "api": 1, "worker": 1},
    )
    assert drain["status"] == "passed"

    ecs.stale_runtime = "worker"
    with pytest.raises(ReadinessFailure, match="unapproved standalone"):
        _verify_standalone_task_drain(
            ecs,
            cluster="ai-fde-design-partner",
            task_definition_arns=task_definitions,
            services={
                "web": "web",
                "api": "api",
                "worker": "worker",
                "migration": None,
            },
            service_desired_counts={"web": 1, "api": 1, "worker": 1},
        )

    db_user_arn = (
        "arn:aws:rds-db:us-east-1:123456789012:"
        f"dbuser:db-ABCDEFGHIJKLMNOPQRSTUVWXY/{WORKER_DATABASE_USER}"
    )
    revocation_evidence = _revocation_evidence(db_user_arn)
    denials = _verify_prior_worker_identity_denials(
        FakeIAM(),
        prior_role_arns=[PRIOR_WORKER_TASK_ROLE_ARN],
        current_worker_role_arn=WORKER_TASK_ROLE_ARN,
        db_user_arn=db_user_arn,
        bucket_arn=EVIDENCE_BUCKET_ARN,
        kms_key_arn=EVIDENCE_KMS_KEY_ARN,
        region="us-east-1",
        worker_engagement_id=WORKER_ENGAGEMENT_ID,
        bedrock_model_arn=BEDROCK_MODEL_ARN,
        revocation_evidence=revocation_evidence,
        now=datetime(2026, 9, 4, 18, 2, tzinfo=UTC),
    )
    roles = denials["roles"]
    assert isinstance(roles, list)
    assert roles[0]["role_arn"] == PRIOR_WORKER_TASK_ROLE_ARN
    assert roles[0]["identity_state"] == "retained-quarantined"
    assert roles[0]["iam_get_role"] == "present"
    assert cast(dict[str, object], roles[0]["live_quarantine"])[
        "sole_inline_policy"
    ] is True
    with pytest.raises(ReadinessFailure, match="retains current deployment authority"):
        _verify_prior_worker_identity_denials(
            FakeIAM(allow_prior_current_resources=True),
            prior_role_arns=[PRIOR_WORKER_TASK_ROLE_ARN],
            current_worker_role_arn=WORKER_TASK_ROLE_ARN,
            db_user_arn=db_user_arn,
            bucket_arn=EVIDENCE_BUCKET_ARN,
            kms_key_arn=EVIDENCE_KMS_KEY_ARN,
            region="us-east-1",
            worker_engagement_id=WORKER_ENGAGEMENT_ID,
            bedrock_model_arn=BEDROCK_MODEL_ARN,
            revocation_evidence=revocation_evidence,
            now=datetime(2026, 9, 4, 18, 2, tzinfo=UTC),
        )


def _run_prior_worker_denial_check(
    client: FakeIAM,
    *,
    prior_role_arns: list[str],
    revocation_evidence: dict[str, object],
) -> dict[str, object]:
    db_user_arn = (
        "arn:aws:rds-db:us-east-1:123456789012:"
        f"dbuser:db-ABCDEFGHIJKLMNOPQRSTUVWXY/{WORKER_DATABASE_USER}"
    )
    return _verify_prior_worker_identity_denials(
        client,
        prior_role_arns=prior_role_arns,
        current_worker_role_arn=WORKER_TASK_ROLE_ARN,
        db_user_arn=db_user_arn,
        bucket_arn=EVIDENCE_BUCKET_ARN,
        kms_key_arn=EVIDENCE_KMS_KEY_ARN,
        region="us-east-1",
        worker_engagement_id=WORKER_ENGAGEMENT_ID,
        bedrock_model_arn=BEDROCK_MODEL_ARN,
        revocation_evidence=revocation_evidence,
        now=datetime(2026, 9, 4, 18, 2, tzinfo=UTC),
    )


def test_first_deployment_requires_an_explicit_empty_signed_prior_role_set() -> None:
    db_user_arn = (
        "arn:aws:rds-db:us-east-1:123456789012:"
        f"dbuser:db-ABCDEFGHIJKLMNOPQRSTUVWXY/{WORKER_DATABASE_USER}"
    )
    result = _run_prior_worker_denial_check(
        FakeIAM(),
        prior_role_arns=[],
        revocation_evidence=_revocation_evidence(
            db_user_arn,
            include_role=False,
        ),
    )
    assert result["first_deployment"] is True
    assert result["roles"] == []

    with pytest.raises(ReadinessFailure, match="explicit prior-role set"):
        _run_prior_worker_denial_check(
            FakeIAM(),
            prior_role_arns=[PRIOR_WORKER_TASK_ROLE_ARN],
            revocation_evidence=_revocation_evidence(
                db_user_arn,
                include_role=False,
            ),
        )


def test_deleted_prior_role_requires_signed_post_ttl_proof() -> None:
    db_user_arn = (
        "arn:aws:rds-db:us-east-1:123456789012:"
        f"dbuser:db-ABCDEFGHIJKLMNOPQRSTUVWXY/{WORKER_DATABASE_USER}"
    )
    deleted = _run_prior_worker_denial_check(
        FakeIAM(get_role_error="NoSuchEntity"),
        prior_role_arns=[PRIOR_WORKER_TASK_ROLE_ARN],
        revocation_evidence=_revocation_evidence(
            db_user_arn,
            identity_state="deleted-after-ttl",
        ),
    )
    deleted_roles = cast(list[dict[str, object]], deleted["roles"])
    assert deleted_roles[0]["iam_get_role"] == "NoSuchEntity"

    with pytest.raises(ReadinessFailure, match="live quarantine state"):
        _run_prior_worker_denial_check(
            FakeIAM(get_role_error="NoSuchEntity"),
            prior_role_arns=[PRIOR_WORKER_TASK_ROLE_ARN],
            revocation_evidence=_revocation_evidence(db_user_arn),
        )


def test_prior_role_access_denied_is_not_treated_as_deletion() -> None:
    db_user_arn = (
        "arn:aws:rds-db:us-east-1:123456789012:"
        f"dbuser:db-ABCDEFGHIJKLMNOPQRSTUVWXY/{WORKER_DATABASE_USER}"
    )
    with pytest.raises(ReadinessFailure, match="could not prove prior worker role"):
        _run_prior_worker_denial_check(
            FakeIAM(get_role_error="AccessDenied"),
            prior_role_arns=[PRIOR_WORKER_TASK_ROLE_ARN],
            revocation_evidence=_revocation_evidence(
                db_user_arn,
                identity_state="deleted-after-ttl",
            ),
        )


@pytest.mark.parametrize(
    "mutation",
    ["trust", "inline", "managed", "profile", "boundary", "cutoff"],
)
def test_retained_prior_role_rejects_live_quarantine_rollback(mutation: str) -> None:
    db_user_arn = (
        "arn:aws:rds-db:us-east-1:123456789012:"
        f"dbuser:db-ABCDEFGHIJKLMNOPQRSTUVWXY/{WORKER_DATABASE_USER}"
    )
    with pytest.raises(ReadinessFailure, match="live quarantine state"):
        _run_prior_worker_denial_check(
            FakeIAM(quarantine_mutation=mutation),
            prior_role_arns=[PRIOR_WORKER_TASK_ROLE_ARN],
            revocation_evidence=_revocation_evidence(db_user_arn),
        )


def test_retained_prior_role_requires_current_denied_probe_evidence() -> None:
    db_user_arn = (
        "arn:aws:rds-db:us-east-1:123456789012:"
        f"dbuser:db-ABCDEFGHIJKLMNOPQRSTUVWXY/{WORKER_DATABASE_USER}"
    )
    with pytest.raises(ReadinessFailure, match="no longer current"):
        _verify_prior_worker_identity_denials(
            FakeIAM(),
            prior_role_arns=[PRIOR_WORKER_TASK_ROLE_ARN],
            current_worker_role_arn=WORKER_TASK_ROLE_ARN,
            db_user_arn=db_user_arn,
            bucket_arn=EVIDENCE_BUCKET_ARN,
            kms_key_arn=EVIDENCE_KMS_KEY_ARN,
            region="us-east-1",
            worker_engagement_id=WORKER_ENGAGEMENT_ID,
            bedrock_model_arn=BEDROCK_MODEL_ARN,
            revocation_evidence=_revocation_evidence(db_user_arn),
            now=datetime(2026, 9, 4, 19, 0, tzinfo=UTC),
        )


def test_ecs_rejects_unsettled_and_surplus_service_inventory() -> None:
    under_count = FakeECS()
    under_count.running_count = 0
    with pytest.raises(ReadinessFailure, match="exact stable count"):
        _verify_fake_ecs(under_count)

    pending = FakeECS()
    pending.pending_count = 1
    with pytest.raises(ReadinessFailure, match="exact stable count"):
        _verify_fake_ecs(pending)

    surplus = FakeECS()
    surplus.surplus_service_task = True
    ecs_check = _verify_fake_ecs(surplus)
    with pytest.raises(ReadinessFailure, match="does not equal desired count"):
        _verify_standalone_task_drain(
            surplus,
            cluster="ai-fde-design-partner",
            task_definition_arns=cast(
                dict[str, str], ecs_check["task_definition_arns"]
            ),
            services={
                "web": "web",
                "api": "api",
                "worker": "worker",
                "migration": None,
            },
            service_desired_counts={"web": 1, "api": 1, "worker": 1},
        )


@pytest.mark.parametrize(
    ("runtime_name", "prior_revision", "classification"),
    [
        ("worker", False, "current-service-revision"),
        ("worker", True, "prior-service-revision"),
        ("migration", False, "migration"),
        ("other", False, "other"),
    ],
)
def test_ecs_classifies_fully_stopped_history_without_blocking_release(
    runtime_name: str,
    prior_revision: bool,
    classification: str,
) -> None:
    ecs = FakeECS()
    ecs.stopped_runtime = runtime_name
    ecs.stopped_prior_revision = prior_revision
    ecs_check = _verify_fake_ecs(ecs)
    task_definitions = cast(dict[str, str], ecs_check["task_definition_arns"])
    result = _verify_standalone_task_drain(
        ecs,
        cluster="ai-fde-design-partner",
        task_definition_arns=task_definitions,
        services={"web": "web", "api": "api", "worker": "worker", "migration": None},
        service_desired_counts={"web": 1, "api": 1, "worker": 1},
    )
    stopped = cast(list[dict[str, object]], result["cluster_stopped_task_history"])
    assert stopped[0]["classification"] == classification


def test_activation_accepts_new_pending_migration_history_but_rejects_active_rogue() -> None:
    candidate = FakeECS()
    candidate_ecs = _verify_fake_ecs(candidate)
    candidate_drain = _verify_standalone_task_drain(
        candidate,
        cluster="ai-fde-design-partner",
        task_definition_arns=cast(
            dict[str, str], candidate_ecs["task_definition_arns"]
        ),
        services={"web": "web", "api": "api", "worker": "worker", "migration": None},
        service_desired_counts={"web": 1, "api": 1, "worker": 1},
    )

    activation = FakeECS()
    activation.migration_revision = 2
    activation.stopped_runtime = "migration"
    activation_ecs = _verify_fake_ecs(activation)
    activation_drain = _verify_standalone_task_drain(
        activation,
        cluster="ai-fde-design-partner",
        task_definition_arns=cast(
            dict[str, str], activation_ecs["task_definition_arns"]
        ),
        services={"web": "web", "api": "api", "worker": "worker", "migration": None},
        service_desired_counts={"web": 1, "api": 1, "worker": 1},
        require_successful_migration=True,
    )
    _verify_standalone_task_drain_transition(
        cast(dict[str, Any], candidate_drain), activation_drain
    )
    migration_tasks = cast(
        list[dict[str, object]], activation_drain["migration_tasks"]
    )
    assert migration_tasks[0]["task_definition_arn"] == activation.task_definition_arn(
        "migration"
    )
    assert migration_tasks[0]["container_exit_code"] == 0

    failed_migration = FakeECS()
    failed_migration.migration_revision = 2
    failed_migration.stopped_runtime = "migration"
    failed_migration.migration_exit_code = 1
    failed_ecs = _verify_fake_ecs(failed_migration)
    with pytest.raises(ReadinessFailure, match="successful migration"):
        _verify_standalone_task_drain(
            failed_migration,
            cluster="ai-fde-design-partner",
            task_definition_arns=cast(
                dict[str, str], failed_ecs["task_definition_arns"]
            ),
            services={
                "web": "web",
                "api": "api",
                "worker": "worker",
                "migration": None,
            },
            service_desired_counts={"web": 1, "api": 1, "worker": 1},
            require_successful_migration=True,
        )

    rogue = FakeECS()
    rogue.stale_runtime = "worker"
    rogue_ecs = _verify_fake_ecs(rogue)
    with pytest.raises(ReadinessFailure, match="unapproved standalone"):
        _verify_standalone_task_drain(
            rogue,
            cluster="ai-fde-design-partner",
            task_definition_arns=cast(
                dict[str, str], rogue_ecs["task_definition_arns"]
            ),
            services={
                "web": "web",
                "api": "api",
                "worker": "worker",
                "migration": None,
            },
            service_desired_counts={"web": 1, "api": 1, "worker": 1},
        )


def test_ecs_rejects_desired_stopped_task_whose_runtime_is_still_running() -> None:
    ecs = FakeECS()
    ecs.stopped_runtime = "worker"
    ecs_check = _verify_fake_ecs(ecs)
    task_definitions = cast(dict[str, str], ecs_check["task_definition_arns"])

    ecs.stopped_last_status = "RUNNING"
    with pytest.raises(ReadinessFailure, match="not fully stopped"):
        _verify_standalone_task_drain(
            ecs,
            cluster="ai-fde-design-partner",
            task_definition_arns=task_definitions,
            services={
                "web": "web",
                "api": "api",
                "worker": "worker",
                "migration": None,
            },
            service_desired_counts={"web": 1, "api": 1, "worker": 1},
        )


class FakeEC2:
    def __init__(
        self,
        *,
        public_subnet: bool = False,
        public_route: bool = False,
        unexpected_egress: bool = False,
        wrong_endpoint_policy: bool = False,
        wrong_endpoint_subnet: bool = False,
        wrong_endpoint_security_group: bool = False,
        wrong_s3_route_table: bool = False,
        broad_endpoint_rule: bool = False,
    ) -> None:
        self.public_subnet = public_subnet
        self.public_route = public_route
        self.unexpected_egress = unexpected_egress
        self.wrong_endpoint_policy = wrong_endpoint_policy
        self.wrong_endpoint_subnet = wrong_endpoint_subnet
        self.wrong_endpoint_security_group = wrong_endpoint_security_group
        self.wrong_s3_route_table = wrong_s3_route_table
        self.broad_endpoint_rule = broad_endpoint_rule

    def describe_subnets(self, *, SubnetIds: list[str]) -> dict[str, object]:
        return {
            "Subnets": [
                {
                    "SubnetId": subnet_id,
                    "VpcId": "vpc-11111111",
                    "MapPublicIpOnLaunch": self.public_subnet,
                }
                for subnet_id in SubnetIds
            ]
        }

    def describe_route_tables(self, *, RouteTableIds: list[str]) -> dict[str, object]:
        routes: list[dict[str, object]] = [
            {
                "DestinationCidrBlock": "10.0.0.0/16",
                "GatewayId": "local",
                "State": "active",
            },
            {
                "DestinationPrefixListId": "pl-77777777",
                "GatewayId": "vpce-00000001",
                "State": "active",
            },
        ]
        if self.public_route:
            routes.append(
                {
                    "DestinationCidrBlock": "0.0.0.0/0",
                    "NatGatewayId": "nat-99999999",
                    "State": "active",
                }
            )
        return {
            "RouteTables": [
                {
                    "RouteTableId": RouteTableIds[0],
                    "VpcId": "vpc-11111111",
                    "Associations": [
                        {"SubnetId": "subnet-33333333"},
                        {"SubnetId": "subnet-44444444"},
                    ],
                    "Routes": routes,
                }
            ]
        }

    def describe_security_group_rules(self, **request: object) -> dict[str, object]:
        filters = cast(list[dict[str, object]], request["Filters"])
        group_id = cast(list[str], filters[0]["Values"])[0]
        if group_id == "sg-77777777":
            endpoint_rules: list[dict[str, object]] = [
                {
                    "IsEgress": False,
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443,
                    "ReferencedGroupInfo": {"GroupId": source_group_id},
                }
                for source_group_id in ["sg-api", "sg-migration", "sg-web", "sg-worker"]
            ]
            if self.broad_endpoint_rule:
                endpoint_rules.append(
                    {
                        "IsEgress": False,
                        "IpProtocol": "tcp",
                        "FromPort": 443,
                        "ToPort": 443,
                        "CidrIpv4": "0.0.0.0/0",
                    }
                )
            return {"SecurityGroupRules": endpoint_rules}
        rules: list[dict[str, object]] = [
            {
                "IsEgress": True,
                "IpProtocol": "tcp",
                "FromPort": 5432,
                "ToPort": 5432,
                "ReferencedGroupInfo": {"GroupId": "sg-66666666"},
            },
            {
                "IsEgress": True,
                "IpProtocol": "tcp",
                "FromPort": 443,
                "ToPort": 443,
                "ReferencedGroupInfo": {"GroupId": "sg-77777777"},
            },
            {
                "IsEgress": True,
                "IpProtocol": "tcp",
                "FromPort": 443,
                "ToPort": 443,
                "PrefixListId": "pl-77777777",
            },
            {
                "IsEgress": True,
                "IpProtocol": "udp",
                "FromPort": 53,
                "ToPort": 53,
                "CidrIpv4": "10.0.0.2/32",
            },
            {
                "IsEgress": True,
                "IpProtocol": "tcp",
                "FromPort": 53,
                "ToPort": 53,
                "CidrIpv4": "10.0.0.2/32",
            },
        ]
        if self.unexpected_egress:
            rules.append(
                {
                    "IsEgress": True,
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443,
                    "CidrIpv4": "0.0.0.0/0",
                }
            )
        return {"SecurityGroupRules": rules}

    def describe_vpc_endpoints(self, *, VpcEndpointIds: list[str]) -> dict[str, object]:
        names = ("s3", "secretsmanager", "bedrock-runtime", "ecr.api", "ecr.dkr", "logs")
        endpoint_by_id = {f"vpce-{index:08x}": name for index, name in enumerate(names, 1)}
        policy: object = {"Version": "2012-10-17", "Statement": []}
        endpoints: list[dict[str, object]] = []
        for endpoint_id in VpcEndpointIds:
            name = endpoint_by_id[endpoint_id]
            live_policy = (
                {"Version": "2012-10-17", "Statement": [{"Effect": "Allow"}]}
                if self.wrong_endpoint_policy and name == "bedrock-runtime"
                else policy
            )
            endpoints.append(
                {
                    "VpcEndpointId": endpoint_id,
                    "VpcId": "vpc-11111111",
                    "ServiceName": f"com.amazonaws.us-east-1.{name}",
                    "VpcEndpointType": "Gateway" if name == "s3" else "Interface",
                    "State": "available",
                    "PrivateDnsEnabled": name != "s3",
                    "PolicyDocument": json.dumps(live_policy),
                    **(
                        {
                            "RouteTableIds": (
                                ["rtb-wrong"]
                                if self.wrong_s3_route_table
                                else ["rtb-private", "rtb-55555555"]
                            )
                        }
                        if name == "s3"
                        else {
                            "SubnetIds": (
                                ["subnet-wrong"]
                                if self.wrong_endpoint_subnet
                                else ["subnet-11111111", "subnet-22222222"]
                            ),
                            "Groups": [
                                {
                                    "GroupId": (
                                        "sg-wrong"
                                        if self.wrong_endpoint_security_group
                                        else "sg-77777777"
                                    )
                                }
                            ],
                        }
                    ),
                }
            )
        return {"VpcEndpoints": endpoints}


def _worker_network_boundary() -> dict[str, object]:
    policy = json.dumps(
        {"Version": "2012-10-17", "Statement": []},
        separators=(",", ":"),
        sort_keys=True,
    )
    policy_digest = "sha256:" + hashlib.sha256(policy.encode()).hexdigest()
    names = ("s3", "secretsmanager", "bedrock-runtime", "ecr.api", "ecr.dkr", "logs")
    return {
        "vpc_id": "vpc-11111111",
        "vpc_cidr": "10.0.0.0/16",
        "worker_security_group_id": "sg-worker",
        "worker_subnet_ids": ["subnet-33333333", "subnet-44444444"],
        "worker_route_table_id": "rtb-55555555",
        "database_security_group_id": "sg-66666666",
        "endpoint_security_group_id": "sg-77777777",
        "endpoint_ingress_security_group_ids": [
            "sg-api",
            "sg-migration",
            "sg-web",
            "sg-worker",
        ],
        "s3_prefix_list_id": "pl-77777777",
        "vpc_resolver_cidr": "10.0.0.2/32",
        "vpc_endpoints": {
            name: {
                "id": f"vpce-{index:08x}",
                "service_name": f"com.amazonaws.us-east-1.{name}",
                "type": "Gateway" if name == "s3" else "Interface",
                "policy_sha256": policy_digest,
                **(
                    {"route_table_ids": ["rtb-55555555", "rtb-private"]}
                    if name == "s3"
                    else {
                        "subnet_ids": ["subnet-11111111", "subnet-22222222"],
                        "security_group_ids": ["sg-77777777"],
                    }
                ),
            }
            for index, name in enumerate(names, 1)
        },
    }


@pytest.mark.parametrize(
    ("client", "message"),
    [
        (FakeEC2(public_subnet=True), "subnet is public"),
        (FakeEC2(public_route=True), "unapproved route"),
        (FakeEC2(unexpected_egress=True), "unapproved egress"),
        (FakeEC2(wrong_endpoint_policy=True), "endpoint bedrock-runtime"),
        (FakeEC2(wrong_endpoint_subnet=True), "attachments differ"),
        (FakeEC2(wrong_endpoint_security_group=True), "attachments differ"),
        (FakeEC2(wrong_s3_route_table=True), "route-table attachments"),
        (FakeEC2(broad_endpoint_rule=True), "broad or unapproved"),
    ],
)
def test_worker_network_rejects_public_or_unapproved_paths(
    client: FakeEC2,
    message: str,
) -> None:
    ecs_check: dict[str, object] = {
        "service_network_configurations": {
            "worker": {
                "security_groups": ["sg-worker"],
                "subnets": ["subnet-33333333", "subnet-44444444"],
                "assign_public_ip": "DISABLED",
            }
        }
    }
    with pytest.raises(ReadinessFailure, match=message):
        _verify_worker_network(
            client,
            ecs_check=ecs_check,
            expected=_worker_network_boundary(),
            region="us-east-1",
        )


def test_worker_network_accepts_only_exact_private_boundary() -> None:
    result = _verify_worker_network(
        FakeEC2(),
        ecs_check={
            "service_network_configurations": {
                "worker": {
                    "security_groups": ["sg-worker"],
                    "subnets": ["subnet-33333333", "subnet-44444444"],
                    "assign_public_ip": "DISABLED",
                }
            }
        },
        expected=_worker_network_boundary(),
        region="us-east-1",
    )
    assert result["public_or_nat_routes"] == 0
    assert result["allowed_egress_rule_count"] == 5


def test_s3_requires_versioning_and_bounded_noncurrent_retention() -> None:
    policy = _evidence_bucket_policy()
    expected = {
        "expected_kms_key_arn": EVIDENCE_KMS_KEY_ARN,
        "expected_bucket_policy_sha256": _policy_sha256(policy),
    }
    result = _verify_s3(FakeS3(policy=policy), "ai-fde-evidence", **expected)
    assert result["versioning"] == "Enabled"
    assert result["noncurrent_retention_days"] == 30
    assert result["kms_key_arn"] == EVIDENCE_KMS_KEY_ARN
    assert result["bucket_policy_sha256"] == expected[
        "expected_bucket_policy_sha256"
    ]

    with pytest.raises(ReadinessFailure, match="versioning"):
        _verify_s3(
            FakeS3(versioning="Disabled", policy=policy),
            "ai-fde-evidence",
            **expected,
        )
    with pytest.raises(ReadinessFailure, match="bounded"):
        _verify_s3(
            FakeS3(retention_days=365, policy=policy),
            "ai-fde-evidence",
            **expected,
        )


def test_s3_rejects_wrong_policy_digest_and_semantically_weak_deny() -> None:
    policy = _evidence_bucket_policy()
    with pytest.raises(ReadinessFailure, match="Terraform policy digest"):
        _verify_s3(
            FakeS3(policy=policy),
            "ai-fde-evidence",
            expected_kms_key_arn=EVIDENCE_KMS_KEY_ARN,
            expected_bucket_policy_sha256="sha256:" + "0" * 64,
        )

    weak_policy = _evidence_bucket_policy()
    statements = cast(list[dict[str, object]], weak_policy["Statement"])
    statements[0]["Condition"] = {
        "Bool": {"aws:SecureTransport": "true"}
    }
    with pytest.raises(ReadinessFailure, match="insecure transport"):
        _verify_s3(
            FakeS3(policy=weak_policy),
            "ai-fde-evidence",
            expected_kms_key_arn=EVIDENCE_KMS_KEY_ARN,
            expected_bucket_policy_sha256=_policy_sha256(weak_policy),
        )


def test_worker_iam_is_bound_to_one_engagement_and_one_bedrock_model() -> None:
    s3_result = _verify_worker_s3_isolation(
        FakeIAM(),
        role_arn="arn:aws:iam::123456789012:role/worker-task",
        bucket_arn=EVIDENCE_BUCKET_ARN,
        kms_key_arn=EVIDENCE_KMS_KEY_ARN,
        region="us-east-1",
        worker_engagement_id=WORKER_ENGAGEMENT_ID,
    )
    assert s3_result["assigned_prefix_get_object"] == "allowed"
    assert s3_result["assigned_prefix_get_object_version"] == "allowed"
    assert s3_result["cross_engagement_get_object"] == "denied"
    assert s3_result["list_bucket"] == "denied"

    bedrock_result = _verify_worker_bedrock_isolation(
        FakeIAM(),
        role_arn="arn:aws:iam::123456789012:role/worker-task",
        model_arn=BEDROCK_MODEL_ARN,
    )
    assert bedrock_result["configured_model_invoke"] == "allowed"
    assert bedrock_result["alternate_model_invoke"] == "denied"

    with pytest.raises(ReadinessFailure, match="different engagement"):
        _verify_worker_s3_isolation(
            FakeIAM(allow_cross_engagement=True),
            role_arn="arn:aws:iam::123456789012:role/worker-task",
            bucket_arn=EVIDENCE_BUCKET_ARN,
            kms_key_arn=EVIDENCE_KMS_KEY_ARN,
            region="us-east-1",
            worker_engagement_id=WORKER_ENGAGEMENT_ID,
        )
    with pytest.raises(ReadinessFailure, match="enumerate"):
        _verify_worker_s3_isolation(
            FakeIAM(allow_bucket_enumeration=True),
            role_arn="arn:aws:iam::123456789012:role/worker-task",
            bucket_arn=EVIDENCE_BUCKET_ARN,
            kms_key_arn=EVIDENCE_KMS_KEY_ARN,
            region="us-east-1",
            worker_engagement_id=WORKER_ENGAGEMENT_ID,
        )
    with pytest.raises(ReadinessFailure, match="mutate"):
        _verify_worker_s3_isolation(
            FakeIAM(allow_worker_mutation=True),
            role_arn="arn:aws:iam::123456789012:role/worker-task",
            bucket_arn=EVIDENCE_BUCKET_ARN,
            kms_key_arn=EVIDENCE_KMS_KEY_ARN,
            region="us-east-1",
            worker_engagement_id=WORKER_ENGAGEMENT_ID,
        )
    with pytest.raises(ReadinessFailure, match="outside S3"):
        _verify_worker_s3_isolation(
            FakeIAM(allow_direct_kms=True),
            role_arn="arn:aws:iam::123456789012:role/worker-task",
            bucket_arn=EVIDENCE_BUCKET_ARN,
            kms_key_arn=EVIDENCE_KMS_KEY_ARN,
            region="us-east-1",
            worker_engagement_id=WORKER_ENGAGEMENT_ID,
        )
    with pytest.raises(ReadinessFailure, match="outside the configured ARN"):
        _verify_worker_bedrock_isolation(
            FakeIAM(allow_alternate_model=True),
            role_arn="arn:aws:iam::123456789012:role/worker-task",
            model_arn=BEDROCK_MODEL_ARN,
        )


def test_worker_database_authentication_rejects_an_old_deployment_identity() -> None:
    current_worker_role = "arn:aws:iam::123456789012:role/worker-task"
    task_roles = {
        "web": "arn:aws:iam::123456789012:role/web-task",
        "api": "arn:aws:iam::123456789012:role/api-task",
        "worker": current_worker_role,
        "migration": "arn:aws:iam::123456789012:role/migration-task",
    }
    result = _verify_worker_database_identity(
        FakeIAM(),
        task_role_arns=task_roles,
        expected_worker_role_arn=current_worker_role,
        db_user_arn=(
            "arn:aws:rds-db:us-east-1:123456789012:"
            f"dbuser:db-ABCDEFGHIJKLMNOPQRSTUVWXY/{WORKER_DATABASE_USER}"
        ),
    )
    assert result["worker_connect"] == "allowed"
    assert result["non_worker_connect"] == "denied"

    with pytest.raises(ReadinessFailure, match="exact workload role"):
        _verify_worker_database_identity(
            FakeIAM(),
            task_role_arns={
                **task_roles,
                "worker": "arn:aws:iam::123456789012:role/old-worker-task",
            },
            expected_worker_role_arn=current_worker_role,
            db_user_arn=(
                "arn:aws:rds-db:us-east-1:123456789012:"
                f"dbuser:db-ABCDEFGHIJKLMNOPQRSTUVWXY/{WORKER_DATABASE_USER}"
            ),
        )


def test_activation_rechecks_all_current_worker_iam_boundaries() -> None:
    task_roles = {
        "web": "arn:aws:iam::123456789012:role/web-task",
        "api": "arn:aws:iam::123456789012:role/api-task",
        "worker": WORKER_TASK_ROLE_ARN,
        "migration": "arn:aws:iam::123456789012:role/migration-task",
    }
    db_user_arn = (
        "arn:aws:rds-db:us-east-1:123456789012:"
        f"dbuser:db-ABCDEFGHIJKLMNOPQRSTUVWXY/{WORKER_DATABASE_USER}"
    )
    qualified_s3 = _verify_worker_s3_isolation(
        FakeIAM(),
        role_arn=WORKER_TASK_ROLE_ARN,
        bucket_arn=EVIDENCE_BUCKET_ARN,
        kms_key_arn=EVIDENCE_KMS_KEY_ARN,
        region="us-east-1",
        worker_engagement_id=WORKER_ENGAGEMENT_ID,
    )
    qualified_bedrock = _verify_worker_bedrock_isolation(
        FakeIAM(), role_arn=WORKER_TASK_ROLE_ARN, model_arn=BEDROCK_MODEL_ARN
    )
    qualified_database = _verify_worker_database_identity(
        FakeIAM(),
        task_role_arns=task_roles,
        expected_worker_role_arn=WORKER_TASK_ROLE_ARN,
        db_user_arn=db_user_arn,
    )

    def verify(client: FakeIAM) -> dict[str, object]:
        return _verify_current_worker_iam_boundaries(
            client,
            task_role_arns=task_roles,
            expected_worker_role_arn=WORKER_TASK_ROLE_ARN,
            db_user_arn=db_user_arn,
            bucket_arn=EVIDENCE_BUCKET_ARN,
            kms_key_arn=EVIDENCE_KMS_KEY_ARN,
            region="us-east-1",
            worker_engagement_id=WORKER_ENGAGEMENT_ID,
            bedrock_model_arn=BEDROCK_MODEL_ARN,
            qualified_s3_isolation=qualified_s3,
            qualified_bedrock_isolation=qualified_bedrock,
            qualified_database_identity=qualified_database,
        )

    assert verify(FakeIAM())["worker_database_identity"] == qualified_database
    with pytest.raises(ReadinessFailure, match="different engagement"):
        verify(FakeIAM(allow_cross_engagement=True))
    with pytest.raises(ReadinessFailure, match="outside the configured ARN"):
        verify(FakeIAM(allow_alternate_model=True))
    with pytest.raises(ReadinessFailure, match="non-worker runtime"):
        verify(FakeIAM(allow_non_worker_rds=True))


def test_activation_rejects_sanitized_data_configuration_mismatch() -> None:
    with pytest.raises(ReadinessFailure, match="SANITIZED_DATA_ENABLED"):
        _verify_ecs(
            FakeECS(),
            cluster="alpha",
            services=["web", "api", "worker"],
            expected_migration_task_definition_arn=MIGRATION_TASK_DEFINITION_ARN,
            expected_images=IMAGES,
            expected_release_revision="a" * 40,
            expected_deployment_id="deploy-2026-09-04-a",
            expected_qualification_mode="controlled-design-partner",
            expected_bedrock_model_id="profile-v1",
            expected_bedrock_classifications=["INTERNAL", "PUBLIC"],
            expected_secret_arns=SECRET_ARNS,
            expected_secret_version_ids=SECRET_VERSION_IDS,
            expected_task_role_arns=TASK_ROLE_ARNS,
            expected_execution_role_arns=EXECUTION_ROLE_ARNS,
            expected_sanitized_data_enabled=True,
        )


def test_activation_requires_the_exact_qualification_secret_version() -> None:
    client = FakeECS()
    client.sanitized_data_enabled = True
    client.qualification_secret_arn = (
        "arn:aws:secretsmanager:us-east-1:123456789012:"
        "secret:ai-fde/qualification-AbCdEf"
    )
    client.qualification_version_id = "a" * 64
    result = _verify_ecs(
        client,
        cluster="alpha",
        services=["web", "api", "worker"],
        expected_migration_task_definition_arn=MIGRATION_TASK_DEFINITION_ARN,
        expected_images=IMAGES,
        expected_release_revision="a" * 40,
        expected_deployment_id="deploy-2026-09-04-a",
        expected_qualification_mode="controlled-design-partner",
        expected_bedrock_model_id="profile-v1",
        expected_bedrock_classifications=["INTERNAL", "PUBLIC"],
        expected_secret_arns=SECRET_ARNS,
        expected_secret_version_ids=SECRET_VERSION_IDS,
        expected_task_role_arns=TASK_ROLE_ARNS,
        expected_execution_role_arns=EXECUTION_ROLE_ARNS,
        expected_sanitized_data_enabled=True,
        expected_qualification_secret_arn=client.qualification_secret_arn,
        expected_qualification_version_id=client.qualification_version_id,
    )
    assert result["qualification_version_id"] == "a" * 64

    with pytest.raises(ReadinessFailure, match="QUALIFICATION_RECORD_VERSION_ID"):
        _verify_ecs(
            client,
            cluster="alpha",
            services=["web", "api", "worker"],
            expected_migration_task_definition_arn=MIGRATION_TASK_DEFINITION_ARN,
            expected_images=IMAGES,
            expected_release_revision="a" * 40,
            expected_deployment_id="deploy-2026-09-04-a",
            expected_qualification_mode="controlled-design-partner",
            expected_bedrock_model_id="profile-v1",
            expected_bedrock_classifications=["INTERNAL", "PUBLIC"],
            expected_secret_arns=SECRET_ARNS,
            expected_secret_version_ids=SECRET_VERSION_IDS,
            expected_task_role_arns=TASK_ROLE_ARNS,
            expected_execution_role_arns=EXECUTION_ROLE_ARNS,
            expected_sanitized_data_enabled=True,
            expected_qualification_secret_arn=client.qualification_secret_arn,
            expected_qualification_version_id="b" * 64,
        )


def test_rds_latest_restorable_time_must_meet_the_rpo() -> None:
    now = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    result = _verify_rds(
        FakeRDS(now - timedelta(minutes=5)),
        "ai-fde-design-partner",
        maximum_rpo_minutes=15,
        now=now,
    )
    assert result["maximum_rpo_minutes"] == 15

    with pytest.raises(ReadinessFailure, match="15-minute RPO"):
        _verify_rds(
            FakeRDS(now - timedelta(minutes=16)),
            "ai-fde-design-partner",
            maximum_rpo_minutes=15,
            now=now,
        )


def test_rds_live_boundary_rejects_post_qualification_drift() -> None:
    now = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    expected = {
        "identifier": "ai-fde-design-partner",
        "engine": "postgres",
        "vpc_id": "vpc-11111111",
        "database_subnet_ids": ["subnet-11111111", "subnet-22222222"],
        "security_group_ids": ["sg-33333333"],
        "kms_key_arn": EVIDENCE_KMS_KEY_ARN,
        "endpoint_address": "db.example.us-east-1.rds.amazonaws.com",
        "endpoint_port": 5432,
        "database_name": "ai_fde",
        "ca_bundle_path": RDS_CA_BUNDLE_PATH,
        "ca_bundle_sha256": RDS_CA_BUNDLE_SHA256,
    }
    result = _verify_rds(
        FakeRDS(now - timedelta(minutes=5)),
        "ai-fde-design-partner",
        maximum_rpo_minutes=15,
        expected=expected,
        now=now,
    )
    assert result["vpc_id"] == expected["vpc_id"]

    for mutation in ("public", "kms", "subnet"):
        with pytest.raises(
            ReadinessFailure,
            match=(
                "exact Terraform boundary"
                if mutation != "public"
                else "public endpoint"
            ),
        ):
            _verify_rds(
                FakeRDS(now - timedelta(minutes=5), mutation=mutation),
                "ai-fde-design-partner",
                maximum_rpo_minutes=15,
                expected=expected,
                now=now,
            )


def test_bedrock_evaluation_must_be_complete_and_match_the_runtime_model() -> None:
    result = _verify_bedrock_evaluation(FakeBedrock(), "evaluation-v1", "profile-v1")
    assert result["job_status"] == "Completed"
    assert result["model_identifier"] == "profile-v1"

    with pytest.raises(ReadinessFailure, match="not completed"):
        _verify_bedrock_evaluation(FakeBedrock(status="InProgress"), "evaluation-v1", "profile-v1")
    with pytest.raises(ReadinessFailure, match="was not evaluated"):
        _verify_bedrock_evaluation(FakeBedrock(), "evaluation-v1", "profile-v2")
