from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import boto3

from ai_fde.modules.factory_engineer.canonical import canonical_sha256
from ai_fde.modules.runtime.qualification import (
    DeploymentQualificationError,
    validate_deployment_qualification_record,
)
from scripts.verify_design_partner_readiness import (
    RDS_CA_BUNDLE_PATH,
    ReadinessFailure,
    _bind_runtime_secrets_to_ecs,
    _load_ecs_role_boundary,
    _load_qualification_control_boundary,
    _load_rds_boundary,
    _load_worker_network_boundary,
    _rds_safe_projection,
    _require,
    _verify_ecs,
    _verify_ecs_data_role_inventory,
    _verify_evidence_signing_public_key,
    _verify_https,
    _verify_prior_worker_identity_denials,
    _verify_qualification_control_plane,
    _verify_qualification_secret_boundary,
    _verify_qualifier_identity,
    _verify_rds,
    _verify_s3,
    _verify_secret,
    _verify_standalone_task_drain,
    _verify_worker_bedrock_isolation,
    _verify_worker_database_identity,
    _verify_worker_network,
    _verify_worker_s3_isolation,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed post-activation proof that sanitized-data enablement is bound "
            "to one immutable qualification version."
        )
    )
    parser.add_argument("--region", required=True)
    parser.add_argument("--application-url", required=True)
    parser.add_argument("--cluster", required=True)
    parser.add_argument(
        "--ecs-role-boundary",
        type=Path,
        required=True,
        help="Raw JSON from `terraform output -json ecs_role_boundary`.",
    )
    parser.add_argument("--db-instance", required=True)
    parser.add_argument(
        "--rds-boundary",
        type=Path,
        required=True,
        help="Raw JSON from `terraform output -json rds_boundary`.",
    )
    parser.add_argument("--web-service", default="web")
    parser.add_argument("--api-service", default="api")
    parser.add_argument("--worker-service", default="worker")
    parser.add_argument("--migration-task-definition-arn", required=True)
    parser.add_argument("--qualification-secret", required=True)
    parser.add_argument("--qualification-secret-policy-sha256", required=True)
    parser.add_argument(
        "--qualification-control-boundary",
        type=Path,
        required=True,
        help="Raw JSON from `terraform output -json qualification_control_boundary`.",
    )
    parser.add_argument("--qualification-version-id", required=True)
    parser.add_argument("--pending-qualification-version-id", required=True)
    parser.add_argument("--qualifier-role-arn", required=True)
    parser.add_argument("--deployment-role-arn", required=True)
    parser.add_argument("--evidence-kms-key-arn", required=True)
    parser.add_argument("--evidence-bucket-policy-sha256", required=True)
    parser.add_argument(
        "--worker-network-boundary",
        type=Path,
        required=True,
        help="Raw JSON from `terraform output -json worker_network_boundary`.",
    )
    prior_roles = parser.add_mutually_exclusive_group(required=True)
    prior_roles.add_argument(
        "--prior-worker-task-role-arn",
        action="append",
        help="Repeat in sorted order for every superseded release-scoped worker role.",
    )
    prior_roles.add_argument(
        "--no-prior-worker-task-roles",
        action="store_true",
        help="Explicitly attest that this first deployment has no prior worker role.",
    )
    parser.add_argument("--oidc-issuer-url", required=True)
    parser.add_argument("--oidc-client-id", required=True)
    parser.add_argument("--oidc-allowed-email", action="append", required=True)
    parser.add_argument("--output", type=Path)
    return parser


def _record_mapping(value: object, field: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"Qualification record field {field} is not an object.")
    return cast(dict[str, Any], value)


def _verify_standalone_task_drain_transition(
    candidate: dict[str, Any],
    activation: dict[str, object],
) -> None:
    """Compare only identities that cannot legitimately change during bind/activate."""

    _require(
        candidate.get("cluster") == activation.get("cluster")
        and candidate.get("enumerated_desired_statuses")
        == activation.get("enumerated_desired_statuses"),
        "Post-activation ECS cluster inventory identity differs from qualification.",
    )
    candidate_services = _record_mapping(
        candidate.get("services"), "checks.standalone_task_drain.services"
    )
    activation_services = _record_mapping(
        activation.get("services"), "activation.standalone_task_drain.services"
    )
    _require(
        set(candidate_services) == set(activation_services) == {"web", "api", "worker"},
        "Post-activation ECS service identity differs from qualification.",
    )
    for runtime_name in ("web", "api", "worker"):
        candidate_service = _record_mapping(
            candidate_services[runtime_name], f"candidate {runtime_name} service"
        )
        activation_service = _record_mapping(
            activation_services[runtime_name], f"activation {runtime_name} service"
        )
        stable_identity = ("service", "desired_count")
        _require(
            all(
                candidate_service.get(field) == activation_service.get(field)
                for field in stable_identity
            ),
            f"Post-activation {runtime_name} service identity differs from qualification.",
        )
        candidate_definition = str(candidate_service.get("task_definition_arn"))
        activation_definition = str(activation_service.get("task_definition_arn"))
        _require(
            candidate_definition.rsplit(":", maxsplit=1)[0]
            == activation_definition.rsplit(":", maxsplit=1)[0],
            f"Post-activation {runtime_name} task-definition family drifted.",
        )
        if runtime_name == "web":
            _require(
                candidate_definition == activation_definition,
                "The bind/activation sequence unexpectedly changed the web task definition.",
            )
    candidate_migration_definition = str(
        candidate.get("migration_task_definition_arn")
    )
    activation_migration_definition = str(
        activation.get("migration_task_definition_arn")
    )
    _require(
        candidate_migration_definition.rsplit(":", maxsplit=1)[0]
        == activation_migration_definition.rsplit(":", maxsplit=1)[0],
        "Post-activation migration task-definition family drifted.",
    )


def _verify_runtime_secret_transition(
    candidate: dict[str, Any],
    activation: dict[str, dict[str, object]],
) -> None:
    """Permit new task registrations while holding secret versions/selectors exact."""

    _require(
        set(candidate) == set(activation) == {"api", "migration"},
        "Post-activation runtime secret inventory differs from qualification.",
    )
    for runtime_name in ("api", "migration"):
        candidate_secret = _record_mapping(
            candidate[runtime_name], f"candidate {runtime_name} secret"
        )
        activation_secret = activation[runtime_name]
        stable_candidate = {
            key: value
            for key, value in candidate_secret.items()
            if key != "task_definition_registered_at"
        }
        stable_activation = {
            key: value
            for key, value in activation_secret.items()
            if key != "task_definition_registered_at"
        }
        _require(
            stable_activation == stable_candidate,
            f"Post-activation {runtime_name} secret version or selector "
            "differs from qualification.",
        )


def _verify_ecs_role_transition(
    candidate: dict[str, Any],
    activation: dict[str, object],
) -> None:
    """Hold every ECS workload role exact across bind and activation revisions."""

    for field in ("task_role_arns", "execution_role_arns"):
        candidate_roles = _record_mapping(candidate.get(field), f"candidate ECS {field}")
        activation_roles = _record_mapping(
            activation.get(field), f"activation ECS {field}"
        )
        _require(
            candidate_roles == activation_roles,
            f"Post-activation ECS {field} differs from qualification.",
        )


def _verify_current_worker_iam_boundaries(
    client: Any,
    *,
    task_role_arns: dict[str, str],
    expected_worker_role_arn: str,
    db_user_arn: str,
    bucket_arn: str,
    kms_key_arn: str,
    region: str,
    worker_engagement_id: str,
    bedrock_model_arn: str,
    qualified_s3_isolation: dict[str, Any],
    qualified_bedrock_isolation: dict[str, Any],
    qualified_database_identity: dict[str, Any],
) -> dict[str, object]:
    """Re-run every current-worker IAM boundary against the activated release."""

    s3_isolation = _verify_worker_s3_isolation(
        client,
        role_arn=expected_worker_role_arn,
        bucket_arn=bucket_arn,
        kms_key_arn=kms_key_arn,
        region=region,
        worker_engagement_id=worker_engagement_id,
    )
    bedrock_isolation = _verify_worker_bedrock_isolation(
        client,
        role_arn=expected_worker_role_arn,
        model_arn=bedrock_model_arn,
    )
    database_identity = _verify_worker_database_identity(
        client,
        task_role_arns=task_role_arns,
        expected_worker_role_arn=expected_worker_role_arn,
        db_user_arn=db_user_arn,
    )
    _require(
        s3_isolation == qualified_s3_isolation,
        "Post-activation worker S3 isolation differs from qualification.",
    )
    _require(
        bedrock_isolation == qualified_bedrock_isolation,
        "Post-activation worker Bedrock isolation differs from qualification.",
    )
    _require(
        database_identity == qualified_database_identity,
        "Post-activation worker database identity differs from qualification.",
    )
    return {
        "worker_s3_isolation": s3_isolation,
        "worker_bedrock_isolation": bedrock_isolation,
        "worker_database_identity": database_identity,
    }


def main() -> None:
    args = _parser().parse_args()
    _require(
        args.pending_qualification_version_id == args.qualification_version_id,
        "Pending and active qualification record versions must match at activation.",
    )
    if args.output and args.output.exists():
        raise ReadinessFailure(
            "The activation output already exists; refusing to overwrite deployment evidence."
        )

    session = boto3.Session(region_name=args.region)
    identity = session.client("sts").get_caller_identity()
    _verify_qualifier_identity(
        identity,
        qualifier_role_arn=args.qualifier_role_arn,
        deployment_role_arn=args.deployment_role_arn,
    )
    secrets_client = session.client("secretsmanager")
    secret_response = secrets_client.get_secret_value(
        SecretId=args.qualification_secret,
        VersionId=args.qualification_version_id,
    )
    _require(
        secret_response.get("VersionId") == args.qualification_version_id,
        "Secrets Manager returned a different qualification version.",
    )
    raw_record = secret_response.get("SecretString")
    _require(isinstance(raw_record, str), "The qualification version has no JSON SecretString.")
    try:
        untrusted = json.loads(raw_record)
        release = _record_mapping(untrusted.get("release"), "release")
        public_key_claims = _verify_evidence_signing_public_key(
            session.client("kms"),
            signing_key_arn=str(release["evidence_signing_key_arn"]),
        )
        qualification = validate_deployment_qualification_record(
            raw_record,
            expected_version_id=args.qualification_version_id,
            expected_release_revision=str(release["git_commit"]),
            expected_deployment_id=str(release["deployment_id"]),
            expected_qualification_mode=str(release["qualification_mode"]),
            expected_worker_operator_id=UUID(str(release["worker_operator_id"])),
            expected_worker_engagement_id=UUID(str(release["worker_engagement_id"])),
            expected_application_origin=args.application_url,
            expected_oidc_issuer_url=args.oidc_issuer_url,
            expected_oidc_client_id=args.oidc_client_id,
            expected_oidc_allowed_emails=args.oidc_allowed_email,
            expected_region=args.region,
            expected_qualifier_role_arn=args.qualifier_role_arn,
            expected_bedrock_model_id=str(release["bedrock_model_id"]),
            expected_bedrock_classifications=cast(
                list[str], release["bedrock_allowed_data_classifications"]
            ),
            expected_s3_kms_key_arn=args.evidence_kms_key_arn,
            expected_qualification_secret_policy_sha256=(
                args.qualification_secret_policy_sha256
            ),
            expected_evidence_signing_public_key_der_b64=public_key_claims[
                "evidence_signing_public_key_der_b64"
            ],
            expected_evidence_signing_public_key_b64_sha256=public_key_claims[
                "evidence_signing_public_key_b64_sha256"
            ],
        )
    except (KeyError, TypeError, ValueError, DeploymentQualificationError) as error:
        raise ReadinessFailure("The pinned qualification version is invalid.") from error

    record = qualification.record
    checks = _record_mapping(record["checks"], "checks")
    qualified_ecs = _record_mapping(checks.get("ecs"), "checks.ecs")
    runtime_secrets = _record_mapping(checks.get("runtime_secrets"), "checks.runtime_secrets")
    external_evidence = _record_mapping(
        record.get("external_evidence"), "external_evidence"
    )
    rotation_summary = _record_mapping(
        external_evidence.get("secret_rotation"),
        "external_evidence.secret_rotation",
    )
    rotation_envelope = _record_mapping(
        rotation_summary.get("signed_record"),
        "external_evidence.secret_rotation.signed_record",
    )
    rotation_results = _record_mapping(
        rotation_envelope.get("results"),
        "external_evidence.secret_rotation.signed_record.results",
    )
    rds = _record_mapping(checks.get("rds"), "checks.rds")
    live_rds = _verify_rds(
        session.client("rds"),
        args.db_instance,
        maximum_rpo_minutes=int(rds["maximum_rpo_minutes"]),
        expected=_load_rds_boundary(args.rds_boundary),
    )
    _require(
        _rds_safe_projection(live_rds) == _rds_safe_projection(rds),
        "Post-activation RDS safe configuration differs from qualification.",
    )
    worker_database_identity = _record_mapping(
        checks.get("worker_database_identity"),
        "checks.worker_database_identity",
    )
    qualified_worker_s3_isolation = _record_mapping(
        checks.get("worker_s3_isolation"),
        "checks.worker_s3_isolation",
    )
    qualified_worker_bedrock_isolation = _record_mapping(
        checks.get("worker_bedrock_isolation"),
        "checks.worker_bedrock_isolation",
    )
    qualified_s3 = _record_mapping(checks.get("s3"), "checks.s3")
    qualified_worker_network = _record_mapping(
        checks.get("worker_network"), "checks.worker_network"
    )
    qualified_prior_denials = _record_mapping(
        checks.get("prior_worker_identity_denials"),
        "checks.prior_worker_identity_denials",
    )
    qualified_standalone_drain = _record_mapping(
        checks.get("standalone_task_drain"),
        "checks.standalone_task_drain",
    )
    qualified_ecs_data_role_inventory = _record_mapping(
        checks.get("ecs_data_role_inventory"),
        "checks.ecs_data_role_inventory",
    )
    live_s3 = _verify_s3(
        session.client("s3"),
        str(qualified_s3["bucket"]),
        expected_kms_key_arn=args.evidence_kms_key_arn,
        expected_bucket_policy_sha256=args.evidence_bucket_policy_sha256,
    )
    _require(
        live_s3 == qualified_s3,
        "Post-activation evidence bucket controls differ from qualification.",
    )
    secret_arns = {
        runtime_name: str(_record_mapping(check, runtime_name)["secret_arn"])
        for runtime_name, check in runtime_secrets.items()
    }
    live_runtime_secrets = {
        runtime_name: _verify_secret(
            secrets_client,
            secret_arns[runtime_name],
            int(_record_mapping(check, runtime_name)["maximum_age_days"]),
            expected_current_version_id=str(
                rotation_results[f"{runtime_name}_current_version_id"]
            ),
        )
        for runtime_name, check in runtime_secrets.items()
    }
    worker_database_url = (
        f"postgresql+psycopg://{release['worker_database_user']}@"
        f"{rds['endpoint_address']}:{rds['endpoint_port']}/{rds['database_name']}"
        f"?sslmode=verify-full&sslrootcert={RDS_CA_BUNDLE_PATH}"
    )
    qualification_secret_arn = str(secret_response["ARN"])
    live_qualification_secret_boundary = _verify_qualification_secret_boundary(
        secrets_client,
        secret_arn=qualification_secret_arn,
        qualifier_role_arn=args.qualifier_role_arn,
        expected_policy_sha256=args.qualification_secret_policy_sha256,
    )
    qualified_qualification_secret_boundary = _record_mapping(
        checks.get("qualification_secret_boundary"),
        "checks.qualification_secret_boundary",
    )
    _require(
        live_qualification_secret_boundary
        == qualified_qualification_secret_boundary,
        "Post-activation qualification-secret policy differs from qualification.",
    )
    qualified_control_plane = _record_mapping(
        checks.get("qualification_control_plane"),
        "checks.qualification_control_plane",
    )
    live_control_plane = _verify_qualification_control_plane(
        session.client("iam"),
        expected=_load_qualification_control_boundary(
            args.qualification_control_boundary
        ),
        qualifier_role_arn=args.qualifier_role_arn,
        deployment_role_arn=args.deployment_role_arn,
        evidence_issuer_role_arn=str(release["evidence_issuer_role_arn"]),
        signing_key_arn=str(release["evidence_signing_key_arn"]),
        qualification_secret_arn=qualification_secret_arn,
    )
    _require(
        live_control_plane == qualified_control_plane,
        "Post-activation qualification control plane differs from qualification.",
    )
    ecs_role_boundary = _load_ecs_role_boundary(args.ecs_role_boundary)
    task_role_arns = cast(dict[str, str], release["task_role_arns"])
    execution_role_arns = cast(dict[str, str], release["execution_role_arns"])
    _require(
        ecs_role_boundary.get("task_role_arns") == task_role_arns
        and ecs_role_boundary.get("execution_role_arns") == execution_role_arns,
        "The activation Terraform ECS role boundary differs from qualification.",
    )
    ecs_check = _verify_ecs(
        session.client("ecs"),
        cluster=args.cluster,
        services=[args.web_service, args.api_service, args.worker_service],
        expected_migration_task_definition_arn=args.migration_task_definition_arn,
        expected_images=cast(dict[str, str], release["images"]),
        expected_release_revision=str(release["git_commit"]),
        expected_deployment_id=str(release["deployment_id"]),
        expected_qualification_mode=str(release["qualification_mode"]),
        expected_bedrock_model_id=str(release["bedrock_model_id"]),
        expected_bedrock_classifications=cast(
            list[str], release["bedrock_allowed_data_classifications"]
        ),
        expected_secret_arns=secret_arns,
        expected_secret_version_ids={
            role: str(rotation_results[f"{role}_current_version_id"])
            for role in ("api", "migration")
        },
        expected_task_role_arns=task_role_arns,
        expected_execution_role_arns=execution_role_arns,
        expected_worker_operator_id=str(release["worker_operator_id"]),
        expected_worker_engagement_id=str(release["worker_engagement_id"]),
        expected_worker_database_url=worker_database_url,
        expected_qualifier_role_arn=args.qualifier_role_arn,
        expected_sanitized_data_enabled=True,
        expected_qualification_secret_arn=qualification_secret_arn,
        expected_qualification_version_id=args.qualification_version_id,
        expected_application_origin=str(release["application_origin"]),
        expected_oidc_issuer_url=str(release["oidc_issuer_url"]),
        expected_oidc_client_id=str(release["oidc_client_id"]),
        expected_oidc_allowed_emails=cast(list[str], release["oidc_allowed_emails"]),
        expected_s3_bucket=str(qualified_s3["bucket"]),
        expected_s3_kms_key_arn=args.evidence_kms_key_arn,
        expected_qualification_secret_policy_sha256=(
            args.qualification_secret_policy_sha256
        ),
        expected_region=args.region,
        expected_evidence_signing_public_key_der_b64=str(
            release["evidence_signing_public_key_der_b64"]
        ),
        expected_evidence_signing_public_key_b64_sha256=str(
            release["evidence_signing_public_key_b64_sha256"]
        ),
    )
    _verify_ecs_role_transition(qualified_ecs, ecs_check)
    live_ecs_data_role_inventory = _verify_ecs_data_role_inventory(
        session.client("iam"),
        expected=ecs_role_boundary,
        task_role_arns=cast(dict[str, str], ecs_check["task_role_arns"]),
        execution_role_arns=cast(
            dict[str, str], ecs_check["execution_role_arns"]
        ),
    )
    _require(
        live_ecs_data_role_inventory == qualified_ecs_data_role_inventory,
        "Post-activation API/migration IAM role inventory differs from qualification.",
    )
    live_runtime_secrets = _bind_runtime_secrets_to_ecs(
        live_runtime_secrets,
        ecs_check,
    )
    _verify_runtime_secret_transition(
        runtime_secrets,
        live_runtime_secrets,
    )
    worker_network = _verify_worker_network(
        session.client("ec2"),
        ecs_check=ecs_check,
        expected=_load_worker_network_boundary(args.worker_network_boundary),
        region=args.region,
    )
    _require(
        worker_network == qualified_worker_network,
        "Post-activation worker network proof differs from qualification.",
    )
    current_worker_role_arn = str(worker_database_identity["worker_role_arn"])
    partition = str(identity["Arn"]).split(":", maxsplit=2)[1]
    current_worker_boundaries = _verify_current_worker_iam_boundaries(
        session.client("iam"),
        task_role_arns=cast(dict[str, str], ecs_check["task_role_arns"]),
        expected_worker_role_arn=current_worker_role_arn,
        db_user_arn=str(worker_database_identity["db_user_arn"]),
        bucket_arn=f"arn:{partition}:s3:::{qualified_s3['bucket']}",
        kms_key_arn=str(qualified_s3["kms_key_arn"]),
        region=args.region,
        worker_engagement_id=str(release["worker_engagement_id"]),
        bedrock_model_arn=str(release["bedrock_model_arn"]),
        qualified_s3_isolation=qualified_worker_s3_isolation,
        qualified_bedrock_isolation=qualified_worker_bedrock_isolation,
        qualified_database_identity=worker_database_identity,
    )
    prior_worker_identity_denials = _verify_prior_worker_identity_denials(
        session.client("iam"),
        prior_role_arns=args.prior_worker_task_role_arn or [],
        current_worker_role_arn=current_worker_role_arn,
        db_user_arn=str(worker_database_identity["db_user_arn"]),
        bucket_arn=f"arn:{partition}:s3:::{qualified_s3['bucket']}",
        kms_key_arn=str(qualified_s3["kms_key_arn"]),
        region=args.region,
        worker_engagement_id=str(release["worker_engagement_id"]),
        bedrock_model_arn=str(release["bedrock_model_arn"]),
        revocation_evidence=cast(
            dict[str, object],
            _record_mapping(
                record["external_evidence"], "external_evidence"
            )["prior_worker_revocation"],
        ),
    )
    _require(
        prior_worker_identity_denials == qualified_prior_denials,
        "Post-activation prior-worker denials differ from qualification.",
    )
    standalone_task_drain = _verify_standalone_task_drain(
        session.client("ecs"),
        cluster=args.cluster,
        task_definition_arns=cast(dict[str, str], ecs_check["task_definition_arns"]),
        services={
            "web": args.web_service,
            "api": args.api_service,
            "worker": args.worker_service,
            "migration": None,
        },
        service_desired_counts=cast(
            dict[str, int], ecs_check["service_desired_counts"]
        ),
        require_successful_migration=True,
    )
    _verify_standalone_task_drain_transition(
        qualified_standalone_drain,
        standalone_task_drain,
    )
    https_check = _verify_https(
        f"{args.application_url.rstrip('/')}/api/ready",
        expected_release_revision=str(release["git_commit"]),
        expected_deployment_id=str(release["deployment_id"]),
        expected_qualification_mode=str(release["qualification_mode"]),
        expected_sanitized_data_enabled=True,
        expected_validation_id=qualification.validation_id,
        expected_qualification_version_id=qualification.version_id,
        expected_qualification_content_digest=qualification.content_digest,
    )
    activation_record: dict[str, Any] = {
        "schema_version": "design-partner-activation-v1",
        "verified_at": datetime.now(UTC).isoformat(),
        "aws_account_id": identity["Account"],
        "aws_principal_arn": identity["Arn"],
        "region": args.region,
        "status": "passed",
        "qualification_secret_arn": qualification_secret_arn,
        "qualification_version_id": qualification.version_id,
        "qualification_validation_id": qualification.validation_id,
        "qualification_content_digest": qualification.content_digest,
        "checks": {
            "ecs": ecs_check,
            "s3": live_s3,
            "rds": live_rds,
            "runtime_secrets": live_runtime_secrets,
            "qualification_secret_boundary": (
                live_qualification_secret_boundary
            ),
            "qualification_control_plane": live_control_plane,
            "ecs_data_role_inventory": live_ecs_data_role_inventory,
            "worker_network": worker_network,
            **current_worker_boundaries,
            "https": https_check,
            "prior_worker_identity_denials": prior_worker_identity_denials,
            "standalone_task_drain": standalone_task_drain,
        },
    }
    activation_record["content_digest"] = canonical_sha256(activation_record)
    output = json.dumps(activation_record, indent=2, sort_keys=True)
    if args.output:
        try:
            with args.output.open("x", encoding="utf-8") as output_file:
                output_file.write(f"{output}\n")
        except FileExistsError as error:
            raise ReadinessFailure(
                "The activation output already exists; refusing to overwrite deployment evidence."
            ) from error
    print(output)


if __name__ == "__main__":
    main()
