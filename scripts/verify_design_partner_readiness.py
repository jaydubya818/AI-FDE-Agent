from __future__ import annotations

import argparse
import json
import re
import ssl
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import boto3
from botocore.exceptions import ClientError


class ReadinessFailure(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReadinessFailure(message)


def _verify_https(url: str) -> dict[str, object]:
    context = ssl.create_default_context()
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=15, context=context) as response:  # noqa: S310
        _require(response.status == 200, "The public HTTPS health endpoint did not return 200.")
    return {"status": "passed", "url": url}


def _verify_s3(client: Any, bucket: str) -> dict[str, object]:
    public = client.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    _require(
        all(
            public.get(key) is True
            for key in (
                "BlockPublicAcls",
                "IgnorePublicAcls",
                "BlockPublicPolicy",
                "RestrictPublicBuckets",
            )
        ),
        "The evidence bucket does not block every form of public access.",
    )
    rules = client.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"][
        "Rules"
    ]
    algorithm = rules[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
    _require(algorithm == "aws:kms", "The evidence bucket is not KMS encrypted.")
    versioning = client.get_bucket_versioning(Bucket=bucket).get("Status", "Disabled")
    _require(versioning != "Enabled", "S3 versioning must remain disabled for deletion fidelity.")
    return {
        "status": "passed",
        "bucket": bucket,
        "encryption": algorithm,
        "versioning": versioning,
    }


def _verify_rds(client: Any, identifier: str) -> dict[str, object]:
    databases = client.describe_db_instances(DBInstanceIdentifier=identifier)["DBInstances"]
    _require(len(databases) == 1, "The expected RDS instance was not found.")
    database = databases[0]
    _require(database["DBInstanceStatus"] == "available", "RDS is not available.")
    _require(database["PubliclyAccessible"] is False, "RDS has a public endpoint.")
    _require(database["StorageEncrypted"] is True, "RDS storage encryption is disabled.")
    _require(database["MultiAZ"] is True, "RDS Multi-AZ is disabled.")
    _require(database["BackupRetentionPeriod"] >= 7, "RDS backup retention is below seven days.")
    _require(database["DeletionProtection"] is True, "RDS deletion protection is disabled.")
    _require("LatestRestorableTime" in database, "RDS point-in-time restore is not available.")

    parameter_group = database["DBParameterGroups"][0]["DBParameterGroupName"]
    parameters = client.describe_db_parameters(
        DBParameterGroupName=parameter_group,
        Filters=[{"Name": "parameter-name", "Values": ["rds.force_ssl"]}],
    )["Parameters"]
    _require(
        len(parameters) == 1 and parameters[0].get("ParameterValue") == "1",
        "RDS does not force TLS.",
    )
    return {
        "status": "passed",
        "identifier": identifier,
        "multi_az": True,
        "backup_retention_days": database["BackupRetentionPeriod"],
        "latest_restorable_time": database["LatestRestorableTime"].isoformat(),
    }


def _verify_ecs(
    client: Any,
    *,
    cluster: str,
    services: list[str],
    migration_family: str,
    expected_images: dict[str, str],
) -> dict[str, object]:
    response = client.describe_services(cluster=cluster, services=services)
    _require(not response.get("failures"), "One or more ECS services could not be described.")
    described = response["services"]
    _require(len(described) == len(services), "One or more ECS services are missing.")

    task_definitions: list[tuple[str, str]] = []
    for service in described:
        service_name = service["serviceName"]
        _require(
            service["runningCount"] >= service["desiredCount"] > 0,
            f"ECS service {service['serviceName']} is not at desired count.",
        )
        configuration = service["networkConfiguration"]["awsvpcConfiguration"]
        _require(
            configuration.get("assignPublicIp") == "DISABLED",
            f"ECS service {service['serviceName']} assigns public IP addresses.",
        )
        circuit_breaker = service.get("deploymentConfiguration", {}).get(
            "deploymentCircuitBreaker", {}
        )
        _require(
            circuit_breaker.get("enable") is True and circuit_breaker.get("rollback") is True,
            f"ECS service {service_name} does not enable deployment rollback.",
        )
        _require(
            service_name in expected_images, f"No expected image was supplied for {service_name}."
        )
        task_definitions.append((service_name, service["taskDefinition"]))
    migration = client.describe_task_definition(taskDefinition=migration_family)["taskDefinition"]
    task_definitions.append(("migration", migration["taskDefinitionArn"]))

    _require(
        set(expected_images) == {name for name, _task in task_definitions},
        "Expected image names must exactly match web, api, worker, and migration runtimes.",
    )

    roles = []
    execution_roles = []
    resolved_images: dict[str, str] = {}
    for runtime_name, task_definition_arn in task_definitions:
        task = client.describe_task_definition(taskDefinition=task_definition_arn)["taskDefinition"]
        _require("FARGATE" in task["requiresCompatibilities"], "A runtime is not a Fargate task.")
        _require(task["networkMode"] == "awsvpc", "A runtime does not use awsvpc networking.")
        containers = [
            container
            for container in task["containerDefinitions"]
            if container["name"] == runtime_name
        ]
        _require(len(containers) == 1, f"Runtime {runtime_name} has no unique primary container.")
        container = containers[0]
        _require(
            container["image"] == expected_images[runtime_name],
            f"Runtime {runtime_name} does not use the release-bound image digest.",
        )
        _require(
            container.get("versionConsistency") == "enabled",
            f"Runtime {runtime_name} does not enforce ECS image version consistency.",
        )
        resolved_images[runtime_name] = container["image"]
        roles.append(task["taskRoleArn"])
        execution_roles.append(task["executionRoleArn"])
    _require(len(roles) == len(set(roles)), "Runtime task IAM roles are not distinct.")
    _require(
        len(execution_roles) == len(set(execution_roles)),
        "Runtime execution IAM roles are not distinct.",
    )
    return {
        "status": "passed",
        "cluster": cluster,
        "services": services,
        "distinct_task_roles": len(roles),
        "images": resolved_images,
        "deployment_rollback": "enabled",
        "version_consistency": "enabled",
    }


def _verify_bedrock_evaluation(
    client: Any, job_identifier: str, model_identifier: str
) -> dict[str, object]:
    job = client.get_evaluation_job(jobIdentifier=job_identifier)
    _require(job["status"] == "Completed", "The Bedrock evaluation job is not completed.")
    _require(
        job.get("applicationType") == "ModelEvaluation",
        "The Bedrock job is not a model evaluation.",
    )
    evaluated_models = {
        model["bedrockModel"]["modelIdentifier"]
        for model in job.get("inferenceConfig", {}).get("models", [])
        if "bedrockModel" in model and "modelIdentifier" in model["bedrockModel"]
    }
    _require(
        model_identifier in evaluated_models,
        "The configured Bedrock model or inference profile was not evaluated by the supplied job.",
    )
    return {
        "status": "passed",
        "job_arn": job["jobArn"],
        "job_name": job["jobName"],
        "job_status": job["status"],
        "model_identifier": model_identifier,
    }


def _release_inputs(args: argparse.Namespace) -> dict[str, object]:
    _require(
        re.fullmatch(r"[0-9a-f]{40}", args.git_commit) is not None,
        "The release Git commit must be an exact 40-character lowercase SHA.",
    )
    images = {
        "web": args.web_image,
        "api": args.api_image,
        "worker": args.worker_image,
        "migration": args.api_image,
    }
    immutable_image = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
    for runtime_name, image in images.items():
        _require(
            immutable_image.fullmatch(image) is not None,
            f"The {runtime_name} image must be pinned by a sha256 digest.",
        )
    for label, value in {
        "Auth0 validation": args.auth0_validation_id,
        "restore rehearsal": args.restore_rehearsal_id,
        "deletion rehearsal": args.deletion_rehearsal_id,
        "secret rotation": args.secret_rotation_id,
    }.items():
        normalized = value.strip()
        _require(
            len(normalized) >= 8
            and normalized.casefold() not in {"pending", "todo", "unverified", "not-run"},
            f"The {label} evidence identifier is not a completed external record.",
        )
    return {"git_commit": args.git_commit, "images": images}


def _verify_bedrock_logging(client: Any) -> dict[str, object]:
    try:
        response = client.get_model_invocation_logging_configuration()
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code not in {"ResourceNotFoundException", "ModelInvocationLoggingConfigurationNotFound"}:
            raise
        response = {}
    _require(not response.get("loggingConfig"), "Bedrock model invocation logging is enabled.")
    return {"status": "passed", "model_invocation_logging": "disabled"}


def _verify_secret(client: Any, secret_id: str, max_age_days: int) -> dict[str, object]:
    secret = client.describe_secret(SecretId=secret_id)
    changed_at = secret.get("LastChangedDate") or secret["CreatedDate"]
    _require(
        changed_at >= datetime.now(UTC) - timedelta(days=max_age_days),
        f"The runtime secret is older than {max_age_days} days.",
    )
    return {
        "status": "passed",
        "secret_arn": secret["ARN"],
        "last_changed": changed_at.isoformat(),
        "maximum_age_days": max_age_days,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed AWS and external-evidence gate for sanitized design-partner data."
    )
    parser.add_argument("--region", required=True)
    parser.add_argument("--application-url", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--db-instance", required=True)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--web-service", default="web")
    parser.add_argument("--api-service", default="api")
    parser.add_argument("--worker-service", default="worker")
    parser.add_argument("--migration-family", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--worker-image", required=True)
    parser.add_argument("--bedrock-evaluation-job", required=True)
    parser.add_argument("--bedrock-model-id", required=True)
    parser.add_argument("--api-secret", required=True)
    parser.add_argument("--worker-secret", required=True)
    parser.add_argument("--migration-secret", required=True)
    parser.add_argument("--max-secret-age-days", type=int, default=90)
    parser.add_argument("--auth0-validation-id", required=True)
    parser.add_argument("--restore-rehearsal-id", required=True)
    parser.add_argument("--deletion-rehearsal-id", required=True)
    parser.add_argument("--secret-rotation-id", required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    release = _release_inputs(args)
    session = boto3.Session(region_name=args.region)
    identity = session.client("sts").get_caller_identity()
    checks: dict[str, Any] = {
        "https": _verify_https(f"{args.application_url.rstrip('/')}/api/health"),
        "s3": _verify_s3(session.client("s3"), args.bucket),
        "rds": _verify_rds(session.client("rds"), args.db_instance),
        "ecs": _verify_ecs(
            session.client("ecs"),
            cluster=args.cluster,
            services=[args.web_service, args.api_service, args.worker_service],
            migration_family=args.migration_family,
            expected_images=cast(dict[str, str], release["images"]),
        ),
        "bedrock_logging": _verify_bedrock_logging(session.client("bedrock")),
        "bedrock_evaluation": _verify_bedrock_evaluation(
            session.client("bedrock"),
            args.bedrock_evaluation_job,
            args.bedrock_model_id,
        ),
        "runtime_secrets": {
            role: _verify_secret(
                session.client("secretsmanager"), secret_id, args.max_secret_age_days
            )
            for role, secret_id in {
                "api": args.api_secret,
                "worker": args.worker_secret,
                "migration": args.migration_secret,
            }.items()
        },
    }
    secret_arns = [check["secret_arn"] for check in checks["runtime_secrets"].values()]
    _require(len(secret_arns) == len(set(secret_arns)), "Runtime secrets are not role-separated.")
    record = {
        "schema_version": "design-partner-readiness-v2",
        "validation_id": f"dpr-{datetime.now(UTC).date()}-{uuid.uuid4().hex[:12]}",
        "validated_at": datetime.now(UTC).isoformat(),
        "aws_account_id": identity["Account"],
        "aws_principal_arn": identity["Arn"],
        "region": args.region,
        "status": "passed",
        "release": release,
        "external_evidence": {
            "auth0_validation_id": args.auth0_validation_id,
            "restore_rehearsal_id": args.restore_rehearsal_id,
            "deletion_rehearsal_id": args.deletion_rehearsal_id,
            "secret_rotation_id": args.secret_rotation_id,
        },
        "checks": checks,
    }
    output = json.dumps(record, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(f"{output}\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
