from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import boto3
from botocore.exceptions import ClientError

from ai_fde.modules.identity.database import worker_database_user_for_release
from ai_fde.modules.runtime.qualification import (
    MAX_QUALIFICATION_RECORD_BYTES,
    QUALIFICATION_SCHEMA_VERSION,
    qualification_content_digest,
    validate_deployment_qualification_record,
)
from ai_fde.modules.runtime.qualification import (
    readiness_validation_digest as readiness_validation_digest,
)

try:
    from scripts.qualification_evidence import (
        EvidenceRecordError,
        load_and_validate_evidence_record,
    )
except ModuleNotFoundError:  # Direct `python scripts/...` invocation.
    from qualification_evidence import (  # type: ignore[no-redef]
        EvidenceRecordError,
        load_and_validate_evidence_record,
    )

try:
    from scripts.quarantine_prior_worker_role import (
        DEFAULT_MAXIMUM_PROBE_AGE_SECONDS,
        PriorWorkerRoleError,
        verify_live_prior_worker_quarantine,
    )
except ModuleNotFoundError:  # Direct `python scripts/...` invocation.
    from quarantine_prior_worker_role import (  # type: ignore[no-redef]
        DEFAULT_MAXIMUM_PROBE_AGE_SECONDS,
        PriorWorkerRoleError,
        verify_live_prior_worker_quarantine,
    )


class ReadinessFailure(RuntimeError):
    pass


RDS_CA_BUNDLE_PATH = "/opt/ai-fde/certs/aws-rds-global-bundle.pem"
RDS_CA_BUNDLE_SHA256 = "sha256:e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
_IAM_ROLE_ARN_PATTERN = re.compile(
    r"arn:aws(?:-us-gov|-cn|-iso|-iso-b)?:iam::[0-9]{12}:"
    r"role/[A-Za-z0-9+=,.@_/-]{1,512}"
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReadinessFailure(message)


def _utc_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not 20 <= len(value) <= 40:
        raise ReadinessFailure(f"{label} is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReadinessFailure(f"{label} is invalid.") from error
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"{label} is invalid.")
    return parsed.astimezone(UTC)


def _verify_https(
    url: str,
    *,
    expected_release_revision: str,
    expected_deployment_id: str,
    expected_qualification_mode: str,
    expected_sanitized_data_enabled: bool = False,
    expected_validation_id: str | None = None,
    expected_qualification_version_id: str | None = None,
    expected_qualification_content_digest: str | None = None,
) -> dict[str, object]:
    try:
        parsed = urlsplit(url)
        is_public_https = (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.username is None
            and parsed.password is None
            and parsed.query == ""
            and parsed.fragment == ""
        )
    except ValueError:
        is_public_https = False
    _require(is_public_https, "The public health endpoint must be a credential-free HTTPS URL.")
    context = ssl.create_default_context()
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(  # noqa: S310
            request, timeout=15, context=context
        ) as response:
            _require(response.status == 200, "The public HTTPS health endpoint did not return 200.")
            raw = response.read(64 * 1024 + 1)
    except (OSError, urllib.error.URLError) as error:
        raise ReadinessFailure("The public HTTPS health endpoint is unreachable.") from error
    _require(len(raw) <= 64 * 1024, "The public readiness response is unexpectedly large.")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessFailure("The public readiness response is not valid JSON.") from error
    _require(isinstance(payload, dict), "The public readiness response is not a JSON object.")
    expected = {
        "status": "ready",
        "release_revision": expected_release_revision,
        "deployment_id": expected_deployment_id,
        "qualification_mode": expected_qualification_mode,
        "sanitized_data_enabled": expected_sanitized_data_enabled,
        "deployment_validation_id": expected_validation_id,
        "deployment_qualification_record_version_id": expected_qualification_version_id,
        "deployment_qualification_content_digest": expected_qualification_content_digest,
    }
    for key, expected_value in expected.items():
        _require(
            payload.get(key) == expected_value,
            f"The public readiness response does not match release field {key}.",
        )
    dependencies = payload.get("dependencies")
    _require(isinstance(dependencies, dict), "The readiness response has no dependency proof.")
    database = dependencies.get("database")
    _require(
        isinstance(database, dict)
        and database.get("status") == "ready"
        and database.get("tls_ca_path") == RDS_CA_BUNDLE_PATH
        and database.get("tls_ca_sha256") == RDS_CA_BUNDLE_SHA256
        and database.get("observed_tls_ca_sha256") == RDS_CA_BUNDLE_SHA256,
        "The live database dependency is not bound to the pinned AWS RDS CA bundle.",
    )
    return {
        "status": "passed",
        "url": url,
        "readiness_status": "ready",
        "release_revision": expected_release_revision,
        "deployment_id": expected_deployment_id,
        "qualification_mode": expected_qualification_mode,
        "sanitized_data_enabled": expected_sanitized_data_enabled,
        "deployment_validation_id": expected_validation_id,
        "deployment_qualification_record_version_id": expected_qualification_version_id,
        "deployment_qualification_content_digest": expected_qualification_content_digest,
        "database_tls_ca_path": RDS_CA_BUNDLE_PATH,
        "database_tls_ca_sha256": RDS_CA_BUNDLE_SHA256,
        "observed_database_tls_ca_sha256": RDS_CA_BUNDLE_SHA256,
    }


def _string_set(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(value)
    return set()


def _policy_principal_is_all(value: object) -> bool:
    return value == "*" or (
        isinstance(value, dict) and value.get("AWS") == "*" and len(value) == 1
    )


def _verify_s3(
    client: Any,
    bucket: str,
    *,
    expected_kms_key_arn: str,
    expected_bucket_policy_sha256: str,
) -> dict[str, object]:
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
    encryption = rules[0]["ApplyServerSideEncryptionByDefault"]
    algorithm = encryption["SSEAlgorithm"]
    _require(algorithm == "aws:kms", "The evidence bucket is not KMS encrypted.")
    kms_key_arn = encryption.get("KMSMasterKeyID")
    exact_kms_key_arn = re.compile(
        r"^arn:aws(?:-us-gov|-cn|-iso|-iso-b)?:kms:[a-z0-9-]+:[0-9]{12}:"
        r"key/[0-9a-fA-F-]{36}$"
    )
    _require(
        isinstance(kms_key_arn, str)
        and exact_kms_key_arn.fullmatch(kms_key_arn) is not None
        and kms_key_arn == expected_kms_key_arn,
        "The evidence bucket is not bound to the exact Terraform KMS key ARN.",
    )
    kms_partition = expected_kms_key_arn.split(":", maxsplit=2)[1]
    bucket_arn = f"arn:{kms_partition}:s3:::{bucket}"
    policy_text = client.get_bucket_policy(Bucket=bucket).get("Policy")
    _require(
        isinstance(policy_text, str),
        "The evidence bucket has no readable resource policy.",
    )
    policy_sha256 = _canonical_policy_digest(policy_text)
    _require(
        re.fullmatch(r"sha256:[0-9a-f]{64}", expected_bucket_policy_sha256)
        is not None
        and policy_sha256 == expected_bucket_policy_sha256,
        "The live evidence bucket policy differs from the exact Terraform policy digest.",
    )
    try:
        policy = json.loads(policy_text)
    except json.JSONDecodeError as error:
        raise ReadinessFailure("The evidence bucket policy is not valid JSON.") from error
    statements_value = policy.get("Statement") if isinstance(policy, dict) else None
    statements = (
        [statements_value]
        if isinstance(statements_value, dict)
        else statements_value
    )
    _require(
        isinstance(statements, list)
        and all(isinstance(statement, dict) for statement in statements),
        "The evidence bucket policy has no exact statement inventory.",
    )
    statements = cast(list[dict[str, Any]], statements)
    by_sid = {statement.get("Sid"): statement for statement in statements}
    required_sids = {
        "DenyInsecureTransport",
        "DenyMissingSSEKMS",
        "DenyWrongSSEAlgorithm",
        "DenyWrongKMSKey",
    }
    _require(
        set(by_sid) == required_sids and len(by_sid) == len(statements),
        "The evidence bucket policy does not contain the exact required deny controls.",
    )

    insecure = by_sid["DenyInsecureTransport"]
    _require(
        insecure.get("Effect") == "Deny"
        and _string_set(insecure.get("Action")) == {"s3:*"}
        and _string_set(insecure.get("Resource")) == {bucket_arn, f"{bucket_arn}/*"}
        and _policy_principal_is_all(insecure.get("Principal"))
        and insecure.get("Condition")
        == {"Bool": {"aws:SecureTransport": "false"}},
        "The evidence bucket policy does not deny every insecure transport request.",
    )
    required_put_conditions = {
        "DenyMissingSSEKMS": {
            "Null": {
                "s3:x-amz-server-side-encryption-aws-kms-key-id": "true"
            }
        },
        "DenyWrongSSEAlgorithm": {
            "StringNotEquals": {"s3:x-amz-server-side-encryption": "aws:kms"}
        },
        "DenyWrongKMSKey": {
            "StringNotEquals": {
                "s3:x-amz-server-side-encryption-aws-kms-key-id": (
                    expected_kms_key_arn
                )
            }
        },
    }
    for sid, expected_condition in required_put_conditions.items():
        statement = by_sid[sid]
        _require(
            statement.get("Effect") == "Deny"
            and _string_set(statement.get("Action")) == {"s3:PutObject"}
            and _string_set(statement.get("Resource")) == {f"{bucket_arn}/*"}
            and _policy_principal_is_all(statement.get("Principal"))
            and statement.get("Condition") == expected_condition,
            f"The evidence bucket policy control {sid} is not exact.",
        )
    versioning = client.get_bucket_versioning(Bucket=bucket).get("Status", "Disabled")
    _require(versioning == "Enabled", "S3 versioning is not enabled for evidence recovery.")
    lifecycle = client.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", [])
    noncurrent_retention_days = [
        rule.get("NoncurrentVersionExpiration", {}).get("NoncurrentDays")
        for rule in lifecycle
        if rule.get("Status") == "Enabled" and rule.get("NoncurrentVersionExpiration")
    ]
    _require(
        any(isinstance(days, int) and 7 <= days <= 90 for days in noncurrent_retention_days),
        "S3 noncurrent evidence versions do not have bounded 7-90 day expiry.",
    )
    return {
        "status": "passed",
        "bucket": bucket,
        "encryption": algorithm,
        "kms_key_arn": kms_key_arn,
        "bucket_policy_sha256": policy_sha256,
        "secure_transport_required": True,
        "explicit_sse_kms_headers_required": True,
        "versioning": versioning,
        "noncurrent_retention_days": min(
            days for days in noncurrent_retention_days if isinstance(days, int)
        ),
    }


def _verify_rds(
    client: Any,
    identifier: str,
    *,
    maximum_rpo_minutes: int = 15,
    expected: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    databases = client.describe_db_instances(DBInstanceIdentifier=identifier)["DBInstances"]
    _require(len(databases) == 1, "The expected RDS instance was not found.")
    database = databases[0]
    live_subnets = database.get("DBSubnetGroup", {}).get("Subnets", [])
    live_security_groups = database.get("VpcSecurityGroups", [])
    _require(
        isinstance(live_subnets, list) and isinstance(live_security_groups, list),
        "RDS returned an invalid subnet or security-group inventory.",
    )
    live_subnet_ids = [
        subnet["SubnetIdentifier"]
        for subnet in live_subnets
        if isinstance(subnet, dict)
        and isinstance(subnet.get("SubnetIdentifier"), str)
    ]
    live_security_group_ids = [
        group["VpcSecurityGroupId"]
        for group in live_security_groups
        if isinstance(group, dict)
        and isinstance(group.get("VpcSecurityGroupId"), str)
    ]
    if expected is not None:
        expected_keys = {
            "identifier",
            "engine",
            "vpc_id",
            "database_subnet_ids",
            "security_group_ids",
            "kms_key_arn",
            "endpoint_address",
            "endpoint_port",
            "database_name",
            "ca_bundle_path",
            "ca_bundle_sha256",
        }
        _require(
            set(expected) == expected_keys,
            "The Terraform RDS boundary has unexpected fields.",
        )
        expected_subnets = expected["database_subnet_ids"]
        expected_security_groups = expected["security_group_ids"]
        _require(
            expected["identifier"] == identifier
            and expected["engine"] == "postgres"
            and isinstance(expected_subnets, list)
            and len(expected_subnets) >= 2
            and all(isinstance(subnet, str) for subnet in expected_subnets)
            and expected_subnets == sorted(set(expected_subnets))
            and isinstance(expected_security_groups, list)
            and len(expected_security_groups) == 1
            and all(
                isinstance(security_group, str)
                for security_group in expected_security_groups
            )
            and expected_security_groups == sorted(set(expected_security_groups))
            and expected["ca_bundle_path"] == RDS_CA_BUNDLE_PATH
            and expected["ca_bundle_sha256"] == RDS_CA_BUNDLE_SHA256,
            "The Terraform RDS boundary is not exact.",
        )
        assert isinstance(expected_subnets, list)
        assert isinstance(expected_security_groups, list)
        expected_subnet_ids = cast(list[str], expected_subnets)
        expected_security_group_ids = cast(list[str], expected_security_groups)
        _require(
            database.get("DBInstanceIdentifier") == expected["identifier"]
            and database.get("Engine") == expected["engine"]
            and database.get("DBSubnetGroup", {}).get("VpcId")
            == expected["vpc_id"]
            and isinstance(live_subnets, list)
            and sorted(live_subnet_ids) == expected_subnet_ids
            and all(
                isinstance(subnet, dict)
                and subnet.get("SubnetStatus") == "Active"
                for subnet in live_subnets
            )
            and isinstance(live_security_groups, list)
            and sorted(live_security_group_ids) == expected_security_group_ids
            and all(
                isinstance(group, dict) and group.get("Status") == "active"
                for group in live_security_groups
            )
            and database.get("KmsKeyId") == expected["kms_key_arn"]
            and database.get("Endpoint", {}).get("Address")
            == expected["endpoint_address"]
            and database.get("Endpoint", {}).get("Port")
            == expected["endpoint_port"] == 5432
            and database.get("DBName") == expected["database_name"],
            "The live RDS instance differs from the exact Terraform boundary.",
        )
    _require(database["DBInstanceStatus"] == "available", "RDS is not available.")
    _require(database["PubliclyAccessible"] is False, "RDS has a public endpoint.")
    _require(database["StorageEncrypted"] is True, "RDS storage encryption is disabled.")
    _require(database["MultiAZ"] is True, "RDS Multi-AZ is disabled.")
    _require(
        database.get("IAMDatabaseAuthenticationEnabled") is True,
        "RDS IAM database authentication is disabled.",
    )
    _require(
        isinstance(database.get("DbiResourceId"), str) and bool(database["DbiResourceId"]),
        "RDS did not return its immutable database resource ID.",
    )
    _require(database["BackupRetentionPeriod"] >= 7, "RDS backup retention is below seven days.")
    _require(database["DeletionProtection"] is True, "RDS deletion protection is disabled.")
    latest_restorable_time = database.get("LatestRestorableTime")
    _require(
        isinstance(latest_restorable_time, datetime),
        "RDS point-in-time restore is not available.",
    )
    assert isinstance(latest_restorable_time, datetime)
    _require(
        latest_restorable_time.tzinfo is not None,
        "RDS latest restorable time has no timezone.",
    )
    reference_time = now or datetime.now(UTC)
    _require(
        reference_time - timedelta(minutes=maximum_rpo_minutes)
        <= latest_restorable_time
        <= reference_time + timedelta(minutes=5),
        f"RDS latest restorable time is outside the {maximum_rpo_minutes}-minute RPO.",
    )

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
        "latest_restorable_time": latest_restorable_time.isoformat(),
        "maximum_rpo_minutes": maximum_rpo_minutes,
        "iam_database_authentication": "enabled",
        "db_resource_id": database["DbiResourceId"],
        "endpoint_address": database["Endpoint"]["Address"],
        "endpoint_port": database["Endpoint"]["Port"],
        "database_name": database["DBName"],
        "engine": database.get("Engine"),
        "vpc_id": database.get("DBSubnetGroup", {}).get("VpcId"),
        "database_subnet_ids": sorted(live_subnet_ids),
        "security_group_ids": sorted(live_security_group_ids),
        "storage_encrypted": database["StorageEncrypted"],
        "kms_key_arn": database.get("KmsKeyId"),
        "publicly_accessible": database["PubliclyAccessible"],
        "deletion_protection": database["DeletionProtection"],
        "force_ssl": True,
        "ca_bundle_path": RDS_CA_BUNDLE_PATH,
        "ca_bundle_sha256": RDS_CA_BUNDLE_SHA256,
    }


def _rds_safe_projection(check: dict[str, object]) -> dict[str, object]:
    projection = dict(check)
    projection.pop("latest_restorable_time", None)
    return projection


def _exact_named_values(
    values: object,
    *,
    value_key: str,
    runtime_name: str,
    collection_name: str,
) -> dict[str, str]:
    if not isinstance(values, list):
        raise ReadinessFailure(
            f"Runtime {runtime_name} {collection_name} is not a list."
        )
    resolved: dict[str, str] = {}
    for index, item in enumerate(values):
        _require(
            isinstance(item, dict) and set(item) == {"name", value_key},
            f"Runtime {runtime_name} {collection_name} item {index} has an unexpected schema.",
        )
        name = item.get("name")
        value = item.get(value_key)
        _require(
            isinstance(name, str) and bool(name) and isinstance(value, str),
            f"Runtime {runtime_name} {collection_name} item {index} is not a string binding.",
        )
        _require(
            name not in resolved,
            f"Runtime {runtime_name} has duplicate {collection_name} name {name}.",
        )
        resolved[name] = value
    return resolved


def _verify_ecs(
    client: Any,
    *,
    cluster: str,
    services: list[str],
    expected_migration_task_definition_arn: str,
    expected_images: dict[str, str],
    expected_release_revision: str,
    expected_deployment_id: str,
    expected_qualification_mode: str,
    expected_bedrock_model_id: str,
    expected_bedrock_classifications: list[str],
    expected_secret_arns: dict[str, str],
    expected_secret_version_ids: dict[str, str],
    expected_task_role_arns: dict[str, str],
    expected_execution_role_arns: dict[str, str],
    expected_worker_operator_id: str = "70000000-0000-4000-8000-000000000002",
    expected_worker_engagement_id: str = "70000000-0000-4000-8000-000000000001",
    expected_worker_database_url: str | None = None,
    expected_qualifier_role_arn: str = (
        "arn:aws:iam::123456789012:role/ai-fde-qualifier"
    ),
    expected_sanitized_data_enabled: bool = False,
    expected_qualification_secret_arn: str | None = None,
    expected_qualification_version_id: str | None = None,
    expected_application_origin: str = "https://ai-fde.example",
    expected_oidc_issuer_url: str = "https://tenant.example/",
    expected_oidc_client_id: str = "design-partner-client",
    expected_oidc_allowed_emails: list[str] | None = None,
    expected_s3_bucket: str = "ai-fde-evidence",
    expected_s3_kms_key_arn: str = (
        "arn:aws:kms:us-east-1:123456789012:"
        "key/70000000-0000-4000-8000-000000000009"
    ),
    expected_qualification_secret_policy_sha256: str = "sha256:" + "7" * 64,
    expected_region: str = "us-east-1",
    expected_evidence_signing_public_key_der_b64: str = "test-public-key",
    expected_evidence_signing_public_key_b64_sha256: str = (
        "sha256:" + "0" * 64
    ),
) -> dict[str, object]:
    if expected_worker_database_url is None:
        worker_database_user = worker_database_user_for_release(
            expected_deployment_id,
            expected_release_revision,
        )
        expected_worker_database_url = (
            "postgresql+psycopg://"
            f"{worker_database_user}@"
            "db.example.us-east-1.rds.amazonaws.com:5432/ai_fde"
            f"?sslmode=verify-full&sslrootcert={RDS_CA_BUNDLE_PATH}"
        )
    _require(
        (expected_qualification_secret_arn is None)
        == (expected_qualification_version_id is None),
        "Qualification secret ARN and exact version must be supplied together.",
    )
    _require(
        set(expected_secret_version_ids) == {"api", "migration"}
        and all(
            re.fullmatch(r"[A-Za-z0-9-]{32,64}", version_id) is not None
            for version_id in expected_secret_version_ids.values()
        ),
        "Exact signed API and migration secret VersionIds are required.",
    )
    expected_runtime_names = {"web", "api", "worker", "migration"}
    _require(
        isinstance(expected_task_role_arns, dict)
        and isinstance(expected_execution_role_arns, dict)
        and set(expected_task_role_arns) == expected_runtime_names
        and set(expected_execution_role_arns) == expected_runtime_names
        and all(
            isinstance(role_arn, str)
            and _IAM_ROLE_ARN_PATTERN.fullmatch(role_arn) is not None
            for role_arn in (
                *expected_task_role_arns.values(),
                *expected_execution_role_arns.values(),
            )
        )
        and len(set(expected_task_role_arns.values())) == 4
        and len(set(expected_execution_role_arns.values())) == 4
        and set(expected_task_role_arns.values()).isdisjoint(
            expected_execution_role_arns.values()
        ),
        "The Terraform ECS role identity boundary is incomplete or not separated.",
    )
    response = client.describe_services(cluster=cluster, services=services)
    _require(not response.get("failures"), "One or more ECS services could not be described.")
    described = response["services"]
    _require(len(described) == len(services), "One or more ECS services are missing.")

    task_definitions: list[tuple[str, str]] = []
    service_security_groups: list[str] = []
    service_network_configurations: dict[str, object] = {}
    for service in described:
        service_name = service["serviceName"]
        _require(
            service["runningCount"] == service["desiredCount"] > 0
            and service.get("pendingCount") == 0,
            f"ECS service {service['serviceName']} is not at its exact stable count.",
        )
        deployments = service.get("deployments", [])
        primary = [
            deployment
            for deployment in deployments
            if deployment.get("status") == "PRIMARY"
        ]
        _require(
            len(primary) == 1
            and primary[0].get("rolloutState") == "COMPLETED"
            and primary[0].get("taskDefinition") == service["taskDefinition"],
            f"ECS service {service_name} has not completed its primary rollout.",
        )
        _require(
            all(
                deployment is primary[0]
                or (
                    deployment.get("runningCount", 0) == 0
                    and deployment.get("pendingCount", 0) == 0
                )
                for deployment in deployments
            ),
            f"ECS service {service_name} still has old deployment tasks.",
        )
        configuration = service["networkConfiguration"]["awsvpcConfiguration"]
        _require(
            configuration.get("assignPublicIp") == "DISABLED",
            f"ECS service {service['serviceName']} assigns public IP addresses.",
        )
        security_groups = configuration.get("securityGroups", [])
        _require(
            len(security_groups) == 1,
            f"ECS service {service_name} must have one dedicated task security group.",
        )
        service_security_groups.append(security_groups[0])
        subnets = configuration.get("subnets", [])
        _require(
            isinstance(subnets, list)
            and len(subnets) >= 2
            and len(subnets) == len(set(subnets)),
            f"ECS service {service_name} must use distinct multi-AZ subnets.",
        )
        service_network_configurations[service_name] = {
            "security_groups": sorted(security_groups),
            "subnets": sorted(subnets),
            "assign_public_ip": configuration["assignPublicIp"],
        }
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
    _require(
        len(service_security_groups) == len(set(service_security_groups)),
        "Web, API, and worker services must use distinct task security groups.",
    )
    migration = client.describe_task_definition(
        taskDefinition=expected_migration_task_definition_arn
    )["taskDefinition"]
    _require(
        migration.get("taskDefinitionArn")
        == expected_migration_task_definition_arn,
        "ECS returned a different migration task definition than Terraform expected.",
    )
    task_definitions.append(("migration", migration["taskDefinitionArn"]))

    _require(
        set(expected_images) == {name for name, _task in task_definitions},
        "Expected image names must exactly match web, api, worker, and migration runtimes.",
    )

    allowed_emails = expected_oidc_allowed_emails or ["operator@example.com"]
    task_roles: dict[str, str] = {}
    execution_roles: dict[str, str] = {}
    resolved_images: dict[str, str] = {}
    resolved_task_definitions: dict[str, str] = {}
    task_definition_registered_at: dict[str, str] = {}
    runtime_secret_value_from: dict[str, dict[str, str]] = {}
    for runtime_name, task_definition_arn in task_definitions:
        task = client.describe_task_definition(taskDefinition=task_definition_arn)["taskDefinition"]
        registered_at = task.get("registeredAt")
        _require(
            isinstance(registered_at, datetime)
            and registered_at.tzinfo is not None
            and registered_at.utcoffset() is not None,
            f"Runtime {runtime_name} task definition has no valid registration time.",
        )
        assert isinstance(registered_at, datetime)
        _require("FARGATE" in task["requiresCompatibilities"], "A runtime is not a Fargate task.")
        _require(task["networkMode"] == "awsvpc", "A runtime does not use awsvpc networking.")
        containers = task["containerDefinitions"]
        _require(
            isinstance(containers, list)
            and len(containers) == 1
            and containers[0].get("name") == runtime_name,
            f"Runtime {runtime_name} must contain exactly one named container.",
        )
        container = containers[0]
        _require(
            container["image"] == expected_images[runtime_name],
            f"Runtime {runtime_name} does not use the release-bound image digest.",
        )
        _require(
            task.get("taskRoleArn") == expected_task_role_arns[runtime_name]
            and task.get("executionRoleArn")
            == expected_execution_role_arns[runtime_name],
            f"Runtime {runtime_name} does not use the exact Terraform task and execution roles.",
        )
        _require(
            container.get("versionConsistency") == "enabled",
            f"Runtime {runtime_name} does not enforce ECS image version consistency.",
        )
        environment = _exact_named_values(
            container.get("environment", []),
            value_key="value",
            runtime_name=runtime_name,
            collection_name="environment",
        )
        actual_secrets = _exact_named_values(
            container.get("secrets", []),
            value_key="valueFrom",
            runtime_name=runtime_name,
            collection_name="secrets",
        )
        _require(
            set(environment).isdisjoint(actual_secrets),
            f"Runtime {runtime_name} has a plaintext environment binding that shadows a secret.",
        )
        if runtime_name == "web":
            expected_environment = {
                "NODE_ENV": "production",
                "HOSTNAME": "0.0.0.0",
                "PORT": "3000",
                "AI_FDE_RELEASE_REVISION": expected_release_revision,
                "AI_FDE_DEPLOYMENT_ID": expected_deployment_id,
                "AI_FDE_DEPLOYMENT_QUALIFICATION_MODE": expected_qualification_mode,
            }
        else:
            expected_environment = {
                "AI_FDE_ENV": "production",
                "AI_FDE_AUTH_MODE": "oidc",
                "AI_FDE_ALLOWED_ORIGINS": json.dumps(
                    [expected_application_origin], separators=(",", ":")
                ),
                "AI_FDE_COCKPIT_URL": expected_application_origin,
                "AI_FDE_OIDC_ISSUER_URL": expected_oidc_issuer_url,
                "AI_FDE_OIDC_CLIENT_ID": expected_oidc_client_id,
                "AI_FDE_OIDC_REDIRECT_URI": (
                    f"{expected_application_origin}/api/auth/callback"
                ),
                "AI_FDE_OIDC_ALLOWED_EMAILS": json.dumps(
                    sorted(allowed_emails), separators=(",", ":")
                ),
                "AI_FDE_WORKER_OPERATOR_ID": expected_worker_operator_id,
                "AI_FDE_WORKER_ENGAGEMENT_ID": expected_worker_engagement_id,
                "AI_FDE_S3_BUCKET": expected_s3_bucket,
                "AI_FDE_S3_KMS_KEY_ARN": expected_s3_kms_key_arn,
                "AI_FDE_S3_REGION": expected_region,
                "AI_FDE_S3_USE_WORKLOAD_IDENTITY": "true",
                "AI_FDE_EXTRACTION_PROVIDER": "bedrock",
                "AI_FDE_BEDROCK_MODEL_ID": expected_bedrock_model_id,
                "AI_FDE_BEDROCK_REGION": expected_region,
                "AI_FDE_BEDROCK_ALLOWED_DATA_CLASSIFICATIONS": json.dumps(
                    expected_bedrock_classifications, separators=(",", ":")
                ),
                "AI_FDE_WORKER_LEASE_SECONDS": "300",
                "AI_FDE_SANITIZED_DATA_ENABLED": str(
                    expected_sanitized_data_enabled
                ).lower(),
                "AI_FDE_RELEASE_REVISION": expected_release_revision,
                "AI_FDE_DEPLOYMENT_ID": expected_deployment_id,
                "AI_FDE_DEPLOYMENT_QUALIFICATION_MODE": expected_qualification_mode,
                "AI_FDE_DEPLOYMENT_QUALIFICATION_ROLE_ARN": expected_qualifier_role_arn,
                "AI_FDE_QUALIFICATION_SECRET_POLICY_SHA256": (
                    expected_qualification_secret_policy_sha256
                ),
                "AI_FDE_RDS_CA_BUNDLE_PATH": RDS_CA_BUNDLE_PATH,
                "AI_FDE_RDS_CA_BUNDLE_SHA256": RDS_CA_BUNDLE_SHA256,
                "AI_FDE_EVIDENCE_SIGNING_PUBLIC_KEY_DER_B64": (
                    expected_evidence_signing_public_key_der_b64
                ),
                "AI_FDE_EVIDENCE_SIGNING_PUBLIC_KEY_B64_SHA256": (
                    expected_evidence_signing_public_key_b64_sha256
                ),
                "AI_FDE_RUNTIME_ROLE": runtime_name,
            }
            if expected_qualification_version_id is not None:
                expected_environment[
                    "AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD_VERSION_ID"
                ] = expected_qualification_version_id
            else:
                _require(
                    "AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD_VERSION_ID" not in environment,
                    f"Runtime {runtime_name} has an unapproved qualification version.",
                )
        _require(
            "AI_FDE_DEPLOYMENT_VALIDATION_ID" not in environment,
            f"Runtime {runtime_name} accepts an unproven free-form validation ID.",
        )
        if runtime_name == "worker":
            expected_environment.update(
                {
                    "AI_FDE_DATABASE_URL": expected_worker_database_url,
                    "AI_FDE_DATABASE_AUTH_MODE": "rds-iam",
                }
            )
        for variable_name, expected_value in expected_environment.items():
            _require(
                environment.get(variable_name) == expected_value,
                f"Runtime {runtime_name} does not bind {variable_name} to the release.",
            )
        _require(
            set(environment) == set(expected_environment),
            f"Runtime {runtime_name} does not use the exact approved environment allowlist.",
        )
        expected_secret_names = {
            "web": set(),
            "api": {"AI_FDE_DATABASE_URL", "AI_FDE_OIDC_CLIENT_SECRET"},
            "worker": set(),
            "migration": {
                "AI_FDE_MIGRATION_DATABASE_URL",
                "AI_FDE_APP_DATABASE_PASSWORD",
            },
        }[runtime_name]
        if expected_qualification_secret_arn is not None and runtime_name != "web":
            expected_secret_names.add("AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD")
        _require(
            set(actual_secrets) == expected_secret_names,
            f"Runtime {runtime_name} does not use the exact role-scoped secret inventory.",
        )
        expected_runtime_secrets: dict[str, str | None] = {}
        if runtime_name in {"api", "migration"}:
            expected_secret_arn = expected_secret_arns.get(runtime_name)
            expected_secret_version_id = expected_secret_version_ids[runtime_name]
            _require(
                isinstance(expected_secret_arn, str),
                f"No verified role-scoped secret ARN was supplied for {runtime_name}.",
            )
            expected_runtime_secrets.update(
                {
                    name: (
                        f"{expected_secret_arn}:{name}::"
                        f"{expected_secret_version_id}"
                    )
                    for name in expected_secret_names
                    if name != "AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD"
                }
            )
        if expected_qualification_secret_arn is not None and runtime_name != "web":
            expected_runtime_secrets["AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD"] = (
                f"{expected_qualification_secret_arn}:::{expected_qualification_version_id}"
            )
        _require(
            actual_secrets == expected_runtime_secrets,
            f"Runtime {runtime_name} is not wired to exact verified secret versions.",
        )
        if runtime_name in {"api", "migration"}:
            runtime_secret_value_from[runtime_name] = {
                name: value
                for name, value in actual_secrets.items()
                if name != "AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD"
            }
        resolved_images[runtime_name] = container["image"]
        task_roles[runtime_name] = task["taskRoleArn"]
        execution_roles[runtime_name] = task["executionRoleArn"]
        resolved_task_definitions[runtime_name] = task["taskDefinitionArn"]
        task_definition_registered_at[runtime_name] = registered_at.astimezone(
            UTC
        ).isoformat()
    _require(
        len(task_roles) == len(set(task_roles.values())),
        "Runtime task IAM roles are not distinct.",
    )
    _require(
        len(execution_roles) == len(set(execution_roles.values())),
        "Runtime execution IAM roles are not distinct.",
    )
    return {
        "status": "passed",
        "cluster": cluster,
        "services": services,
        "distinct_task_roles": len(task_roles),
        "task_role_arns": task_roles,
        "execution_role_arns": execution_roles,
        "task_definition_arns": resolved_task_definitions,
        "task_definition_registered_at": task_definition_registered_at,
        "service_desired_counts": {
            service["serviceName"]: service["desiredCount"] for service in described
        },
        "service_network_configurations": service_network_configurations,
        "distinct_service_security_groups": len(service_security_groups),
        "images": resolved_images,
        "deployment_rollback": "enabled",
        "version_consistency": "enabled",
        "release_revision": expected_release_revision,
        "deployment_id": expected_deployment_id,
        "qualification_mode": expected_qualification_mode,
        "worker_engagement_id": expected_worker_engagement_id,
        "worker_operator_id": expected_worker_operator_id,
        "sanitized_data_enabled": expected_sanitized_data_enabled,
        "qualification_secret_arn": expected_qualification_secret_arn,
        "qualification_version_id": expected_qualification_version_id,
        "runtime_secret_value_from": runtime_secret_value_from,
    }


def _list_cluster_tasks(
    client: Any,
    *,
    cluster: str,
    desired_status: str,
) -> list[str]:
    task_arns: list[str] = []
    next_token: str | None = None
    for _page in range(20):
        request: dict[str, object] = {
            "cluster": cluster,
            "desiredStatus": desired_status,
        }
        if next_token is not None:
            request["nextToken"] = next_token
        response = client.list_tasks(**request)
        page_arns = response.get("taskArns", [])
        _require(
            isinstance(page_arns, list)
            and all(isinstance(task_arn, str) for task_arn in page_arns),
            f"ECS returned invalid cluster-wide {desired_status} task identifiers.",
        )
        task_arns.extend(page_arns)
        token = response.get("nextToken")
        if token is None:
            break
        _require(isinstance(token, str) and bool(token), "ECS returned an invalid task cursor.")
        next_token = token
    else:
        raise ReadinessFailure("ECS cluster-wide task enumeration exceeded 20 pages.")
    _require(
        len(task_arns) == len(set(task_arns)),
        "ECS returned duplicate cluster-wide task identifiers.",
    )
    return task_arns


def _load_worker_network_boundary(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ReadinessFailure("The Terraform worker network boundary is unreadable.") from error
    _require(
        0 < len(raw) <= 64 * 1024,
        "The Terraform worker network boundary is empty or oversized.",
    )
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessFailure(
            "The Terraform worker network boundary is not valid JSON."
        ) from error
    _require(isinstance(value, dict), "The worker network boundary is not an object.")
    return cast(dict[str, Any], value)


def _load_rds_boundary(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ReadinessFailure("The Terraform RDS boundary is unreadable.") from error
    _require(
        0 < len(raw) <= 16 * 1024,
        "The Terraform RDS boundary is empty or oversized.",
    )
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessFailure("The Terraform RDS boundary is not valid JSON.") from error
    _require(isinstance(value, dict), "The Terraform RDS boundary is not an object.")
    return cast(dict[str, Any], value)


def _load_qualification_control_boundary(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ReadinessFailure(
            "The Terraform qualification control boundary is unreadable."
        ) from error
    _require(
        0 < len(raw) <= 32 * 1024,
        "The Terraform qualification control boundary is empty or oversized.",
    )
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessFailure(
            "The Terraform qualification control boundary is not valid JSON."
        ) from error
    _require(
        isinstance(value, dict),
        "The Terraform qualification control boundary is not an object.",
    )
    return cast(dict[str, Any], value)


def _load_ecs_role_boundary(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ReadinessFailure("The Terraform ECS role boundary is unreadable.") from error
    _require(0 < len(raw) <= 32 * 1024, "The Terraform ECS role boundary is invalid.")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessFailure("The Terraform ECS role boundary is not valid JSON.") from error
    _require(isinstance(value, dict), "The Terraform ECS role boundary is not an object.")
    return cast(dict[str, Any], value)


def _canonical_policy_digest(value: object) -> str:
    try:
        payload = json.loads(value) if isinstance(value, str) else value
        encoded = json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ReadinessFailure("A VPC endpoint policy is not canonical JSON.") from error
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _list_iam_role_values(
    client: Any,
    *,
    operation: str,
    role_name: str,
    response_key: str,
) -> list[object]:
    values: list[object] = []
    marker: str | None = None
    method = getattr(client, operation)
    for _page in range(20):
        request: dict[str, object] = {"RoleName": role_name}
        if marker is not None:
            request["Marker"] = marker
        response = method(**request)
        page_values = response.get(response_key, [])
        _require(
            isinstance(page_values, list),
            f"IAM returned an invalid {response_key} inventory.",
        )
        values.extend(page_values)
        if response.get("IsTruncated") is not True:
            break
        next_marker = response.get("Marker")
        _require(
            isinstance(next_marker, str) and bool(next_marker),
            f"IAM returned an invalid {response_key} cursor.",
        )
        marker = next_marker
    else:
        raise ReadinessFailure(f"IAM {response_key} enumeration exceeded 20 pages.")
    return values


def _verify_ecs_data_role_inventory(
    client: Any,
    *,
    expected: dict[str, Any],
    task_role_arns: dict[str, str],
    execution_role_arns: dict[str, str],
) -> dict[str, object]:
    _require(
        set(expected) == {"task_role_arns", "execution_role_arns", "data_role_contracts"}
        and expected.get("task_role_arns") == task_role_arns
        and expected.get("execution_role_arns") == execution_role_arns,
        "The live ECS roles do not match the exact Terraform role boundary.",
    )
    contracts = expected.get("data_role_contracts")
    expected_roles = {
        "api_task": task_role_arns["api"],
        "api_execution": execution_role_arns["api"],
        "migration_task": task_role_arns["migration"],
        "migration_execution": execution_role_arns["migration"],
    }
    _require(
        isinstance(contracts, dict) and set(contracts) == set(expected_roles),
        "The Terraform API/migration role contracts are incomplete.",
    )
    assert isinstance(contracts, dict)
    observed_roles: dict[str, object] = {}
    for role_kind, role_arn in expected_roles.items():
        contract = contracts.get(role_kind)
        _require(
            isinstance(contract, dict)
            and set(contract)
            == {
                "role_arn",
                "trust_policy_sha256",
                "inline_policy_sha256",
                "attached_managed_policy_arns",
            }
            and contract.get("role_arn") == role_arn
            and _IAM_ROLE_ARN_PATTERN.fullmatch(role_arn) is not None,
            f"The Terraform {role_kind} contract is invalid.",
        )
        assert isinstance(contract, dict)
        trust_digest = contract.get("trust_policy_sha256")
        inline_digests = contract.get("inline_policy_sha256")
        attached_arns = contract.get("attached_managed_policy_arns")
        _require(
            isinstance(trust_digest, str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", trust_digest) is not None
            and isinstance(inline_digests, dict)
            and all(
                isinstance(name, str)
                and bool(name)
                and isinstance(digest, str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None
                for name, digest in inline_digests.items()
            )
            and isinstance(attached_arns, list)
            and all(isinstance(arn, str) and "*" not in arn for arn in attached_arns)
            and attached_arns == sorted(set(attached_arns)),
            f"The Terraform {role_kind} policy inventory is invalid.",
        )
        assert isinstance(inline_digests, dict) and isinstance(attached_arns, list)
        role_name = role_arn.rsplit("/", maxsplit=1)[-1]
        role = client.get_role(RoleName=role_name).get("Role")
        _require(
            isinstance(role, dict)
            and role.get("Arn") == role_arn
            and role.get("PermissionsBoundary") is None
            and _canonical_policy_digest(role.get("AssumeRolePolicyDocument"))
            == trust_digest,
            f"The live {role_kind} trust or permissions boundary drifted.",
        )
        inline_names_raw = _list_iam_role_values(
            client,
            operation="list_role_policies",
            role_name=role_name,
            response_key="PolicyNames",
        )
        _require(
            all(isinstance(name, str) for name in inline_names_raw)
            and sorted(cast(list[str], inline_names_raw)) == sorted(inline_digests),
            f"The live {role_kind} inline-policy inventory drifted.",
        )
        observed_inline: dict[str, str] = {}
        for policy_name, expected_digest in inline_digests.items():
            observed_digest = _canonical_policy_digest(
                client.get_role_policy(
                    RoleName=role_name,
                    PolicyName=policy_name,
                ).get("PolicyDocument")
            )
            _require(
                observed_digest == expected_digest,
                f"The live {role_kind} inline policy {policy_name} drifted.",
            )
            observed_inline[policy_name] = observed_digest
        attached_raw = _list_iam_role_values(
            client,
            operation="list_attached_role_policies",
            role_name=role_name,
            response_key="AttachedPolicies",
        )
        observed_attached = sorted(
            item["PolicyArn"]
            for item in attached_raw
            if isinstance(item, dict) and isinstance(item.get("PolicyArn"), str)
        )
        profiles = _list_iam_role_values(
            client,
            operation="list_instance_profiles_for_role",
            role_name=role_name,
            response_key="InstanceProfiles",
        )
        _require(
            len(observed_attached) == len(attached_raw)
            and observed_attached == attached_arns
            and profiles == [],
            f"The live {role_kind} managed-policy or instance-profile inventory drifted.",
        )
        observed_roles[role_kind] = {
            "role_arn": role_arn,
            "trust_policy_sha256": trust_digest,
            "inline_policy_sha256": observed_inline,
            "attached_managed_policy_arns": observed_attached,
            "permissions_boundary_present": False,
            "instance_profile_arns": [],
        }
    return {
        "status": "passed",
        "task_role_arns": task_role_arns,
        "execution_role_arns": execution_role_arns,
        "roles": observed_roles,
    }


_QUALIFICATION_SECRET_MUTATIONS = (
    "secretsmanager:DeleteResourcePolicy",
    "secretsmanager:DeleteSecret",
    "secretsmanager:PutResourcePolicy",
    "secretsmanager:PutSecretValue",
    "secretsmanager:RotateSecret",
    "secretsmanager:UpdateSecret",
    "secretsmanager:UpdateSecretVersionStage",
)


def _verify_qualification_control_plane(
    client: Any,
    *,
    expected: dict[str, Any],
    qualifier_role_arn: str,
    deployment_role_arn: str,
    evidence_issuer_role_arn: str,
    signing_key_arn: str,
    qualification_secret_arn: str,
) -> dict[str, object]:
    _require(
        set(expected) == {"qualification_secret_arn", "signing_key_arn", "roles"}
        and expected.get("qualification_secret_arn") == qualification_secret_arn
        and expected.get("signing_key_arn") == signing_key_arn,
        "The Terraform qualification control boundary does not match the release.",
    )
    role_contracts = expected.get("roles")
    expected_role_arns = {
        "qualifier": qualifier_role_arn,
        "deployment": deployment_role_arn,
        "evidence_issuer": evidence_issuer_role_arn,
    }
    _require(
        isinstance(role_contracts, dict)
        and set(role_contracts) == set(expected_role_arns)
        and len(set(expected_role_arns.values())) == 3,
        "The Terraform qualification role inventory is incomplete or not separated.",
    )
    assert isinstance(role_contracts, dict)
    observed_roles: dict[str, object] = {}
    for role_kind, expected_role_arn in expected_role_arns.items():
        contract = role_contracts.get(role_kind)
        _require(
            isinstance(contract, dict)
            and set(contract)
            == {
                "role_arn",
                "trusted_principal_arn",
                "trust_policy_sha256",
                "inline_policy_sha256",
            }
            and contract.get("role_arn") == expected_role_arn,
            f"The Terraform {role_kind} role contract is invalid.",
        )
        assert isinstance(contract, dict)
        role_match = re.fullmatch(
            r"arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):iam::([0-9]{12}):"
            r"role/[A-Za-z0-9+=,.@_/-]+",
            expected_role_arn,
        )
        trusted_principal_arn = contract.get("trusted_principal_arn")
        _require(
            role_match is not None
            and isinstance(trusted_principal_arn, str)
            and re.fullmatch(
                rf"arn:{re.escape(role_match.group(1))}:iam::{role_match.group(2)}:"
                r"(?:role|user)/[A-Za-z0-9+=,.@_/-]+",
                trusted_principal_arn,
            )
            is not None
            and "*" not in trusted_principal_arn,
            f"The Terraform {role_kind} trusted principal is not an exact account principal.",
        )
        expected_trust_digest = contract.get("trust_policy_sha256")
        expected_inline = contract.get("inline_policy_sha256")
        _require(
            isinstance(expected_trust_digest, str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", expected_trust_digest) is not None
            and isinstance(expected_inline, dict)
            and len(expected_inline) == 1
            and all(
                isinstance(name, str)
                and bool(name)
                and isinstance(digest, str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None
                for name, digest in expected_inline.items()
            ),
            f"The Terraform {role_kind} policy digests are invalid.",
        )
        assert isinstance(expected_inline, dict)
        role_name = expected_role_arn.rsplit("/", maxsplit=1)[-1]
        role_response = client.get_role(RoleName=role_name)
        role = role_response.get("Role")
        _require(
            isinstance(role, dict)
            and role.get("Arn") == expected_role_arn
            and role.get("PermissionsBoundary") is None
            and _canonical_policy_digest(role.get("AssumeRolePolicyDocument"))
            == expected_trust_digest,
            f"The live {role_kind} role trust or permissions boundary drifted.",
        )
        inline_names_raw = _list_iam_role_values(
            client,
            operation="list_role_policies",
            role_name=role_name,
            response_key="PolicyNames",
        )
        _require(
            all(isinstance(name, str) for name in inline_names_raw),
            f"The live {role_kind} inline-policy inventory drifted.",
        )
        inline_names = cast(list[str], inline_names_raw)
        _require(
            sorted(inline_names) == sorted(expected_inline),
            f"The live {role_kind} inline-policy inventory drifted.",
        )
        observed_inline: dict[str, str] = {}
        for policy_name, expected_digest in expected_inline.items():
            policy_response = client.get_role_policy(
                RoleName=role_name,
                PolicyName=policy_name,
            )
            observed_digest = _canonical_policy_digest(
                policy_response.get("PolicyDocument")
            )
            _require(
                observed_digest == expected_digest,
                f"The live {role_kind} inline policy {policy_name} drifted.",
            )
            observed_inline[policy_name] = observed_digest
        attached = _list_iam_role_values(
            client,
            operation="list_attached_role_policies",
            role_name=role_name,
            response_key="AttachedPolicies",
        )
        profiles = _list_iam_role_values(
            client,
            operation="list_instance_profiles_for_role",
            role_name=role_name,
            response_key="InstanceProfiles",
        )
        _require(
            attached == [] and profiles == [],
            f"The live {role_kind} role has an unexpected managed policy or profile.",
        )
        observed_roles[role_kind] = {
            "role_arn": expected_role_arn,
            "trusted_principal_arn": trusted_principal_arn,
            "trust_policy_sha256": expected_trust_digest,
            "inline_policy_sha256": observed_inline,
            "attached_managed_policy_arns": [],
            "instance_profile_arns": [],
            "permissions_boundary_present": False,
        }

    simulations: dict[str, str] = {}
    for role_kind, role_arn in expected_role_arns.items():
        sign_decision = _simulate_iam_decision(
            client,
            role_arn=role_arn,
            action="kms:Sign",
            resource_arn=signing_key_arn,
        )
        expected_sign_allowed = role_kind == "evidence_issuer"
        _require(
            (sign_decision == "allowed") == expected_sign_allowed,
            f"The {role_kind} KMS signing boundary is not exact.",
        )
        simulations[f"{role_kind}_kms_sign"] = (
            "allowed" if expected_sign_allowed else "denied"
        )
        for action in _QUALIFICATION_SECRET_MUTATIONS:
            decision = _simulate_iam_decision(
                client,
                role_arn=role_arn,
                action=action,
                resource_arn=qualification_secret_arn,
            )
            expected_allowed = (
                role_kind == "qualifier"
                and action == "secretsmanager:PutSecretValue"
            )
            _require(
                (decision == "allowed") == expected_allowed,
                f"The {role_kind} qualification-secret mutation boundary is not exact.",
            )
            action_label = action.removeprefix("secretsmanager:")
            simulations[f"{role_kind}_{action_label}"] = (
                "allowed" if expected_allowed else "denied"
            )
    return {
        "status": "passed",
        "qualification_secret_arn": qualification_secret_arn,
        "signing_key_arn": signing_key_arn,
        "roles": observed_roles,
        "simulations": simulations,
    }


def _verify_worker_network(
    client: Any,
    *,
    ecs_check: dict[str, object],
    expected: dict[str, Any],
    region: str,
) -> dict[str, object]:
    expected_keys = {
        "vpc_id",
        "vpc_cidr",
        "worker_security_group_id",
        "worker_subnet_ids",
        "worker_route_table_id",
        "database_security_group_id",
        "endpoint_security_group_id",
        "endpoint_ingress_security_group_ids",
        "s3_prefix_list_id",
        "vpc_resolver_cidr",
        "vpc_endpoints",
    }
    _require(
        set(expected) == expected_keys,
        "The Terraform worker network boundary has unexpected fields.",
    )
    endpoints = expected["vpc_endpoints"]
    required_endpoint_names = {
        "s3",
        "secretsmanager",
        "bedrock-runtime",
        "ecr.api",
        "ecr.dkr",
        "logs",
    }
    _require(
        isinstance(endpoints, dict) and set(endpoints) == required_endpoint_names,
        "The Terraform boundary does not contain every required private endpoint.",
    )
    worker_networks = cast(
        dict[str, dict[str, object]], ecs_check["service_network_configurations"]
    )
    worker_network = worker_networks.get("worker")
    _require(
        isinstance(worker_network, dict)
        and worker_network.get("security_groups")
        == [expected["worker_security_group_id"]]
        and worker_network.get("subnets") == sorted(expected["worker_subnet_ids"])
        and worker_network.get("assign_public_ip") == "DISABLED",
        "The live worker service is not attached to the exact isolated Terraform network.",
    )
    subnet_ids = expected["worker_subnet_ids"]
    _require(
        isinstance(subnet_ids, list)
        and len(subnet_ids) >= 2
        and subnet_ids == sorted(set(subnet_ids)),
        "The Terraform worker subnet inventory is invalid.",
    )
    subnet_response = client.describe_subnets(SubnetIds=subnet_ids)
    subnets = subnet_response.get("Subnets", [])
    _require(
        isinstance(subnets, list)
        and {subnet.get("SubnetId") for subnet in subnets} == set(subnet_ids)
        and all(
            subnet.get("VpcId") == expected["vpc_id"]
            and subnet.get("MapPublicIpOnLaunch") is False
            for subnet in subnets
        ),
        "A worker subnet is public, missing, or belongs to another VPC.",
    )
    route_tables = client.describe_route_tables(
        RouteTableIds=[expected["worker_route_table_id"]]
    ).get("RouteTables", [])
    _require(
        isinstance(route_tables, list) and len(route_tables) == 1,
        "The worker route table is missing or ambiguous.",
    )
    route_table = route_tables[0]
    associated_subnets = {
        association.get("SubnetId")
        for association in route_table.get("Associations", [])
        if association.get("AssociationState", {}).get("State", "associated")
        == "associated"
    }
    _require(
        route_table.get("VpcId") == expected["vpc_id"]
        and associated_subnets == set(subnet_ids),
        "The isolated worker route table is not bound to every exact worker subnet.",
    )
    active_routes = [
        route
        for route in route_table.get("Routes", [])
        if route.get("State", "active") == "active"
    ]
    route_projection = {
        (
            route.get("DestinationCidrBlock"),
            route.get("DestinationPrefixListId"),
            route.get("GatewayId"),
            route.get("NatGatewayId"),
        )
        for route in active_routes
    }
    s3_endpoint_id = cast(dict[str, object], endpoints["s3"])["id"]
    _require(
        route_projection
        == {
            (expected["vpc_cidr"], None, "local", None),
            (None, expected["s3_prefix_list_id"], s3_endpoint_id, None),
        },
        "The worker route table contains a NAT, public, or unapproved route.",
    )
    rules = client.describe_security_group_rules(
        Filters=[
            {
                "Name": "group-id",
                "Values": [expected["worker_security_group_id"]],
            }
        ]
    ).get("SecurityGroupRules", [])
    _require(
        isinstance(rules, list) and all(rule.get("IsEgress") is True for rule in rules),
        "The worker security group has ingress or an invalid rule inventory.",
    )
    rule_projection = {
        (
            rule.get("IpProtocol"),
            rule.get("FromPort"),
            rule.get("ToPort"),
            rule.get("CidrIpv4"),
            rule.get("PrefixListId"),
            (
                rule.get("ReferencedGroupInfo", {}).get("GroupId")
                if isinstance(rule.get("ReferencedGroupInfo"), dict)
                else None
            ),
        )
        for rule in rules
    }
    _require(
        rule_projection
        == {
            ("tcp", 5432, 5432, None, None, expected["database_security_group_id"]),
            ("tcp", 443, 443, None, None, expected["endpoint_security_group_id"]),
            ("tcp", 443, 443, None, expected["s3_prefix_list_id"], None),
            ("udp", 53, 53, expected["vpc_resolver_cidr"], None, None),
            ("tcp", 53, 53, expected["vpc_resolver_cidr"], None, None),
        },
        "The worker security group permits unapproved egress.",
    )
    endpoint_ingress_security_group_ids = expected[
        "endpoint_ingress_security_group_ids"
    ]
    _require(
        isinstance(endpoint_ingress_security_group_ids, list)
        and len(endpoint_ingress_security_group_ids) == 4
        and endpoint_ingress_security_group_ids
        == sorted(set(endpoint_ingress_security_group_ids))
        and expected["worker_security_group_id"]
        in endpoint_ingress_security_group_ids,
        "The Terraform endpoint security-group principal inventory is invalid.",
    )
    endpoint_rules = client.describe_security_group_rules(
        Filters=[
            {
                "Name": "group-id",
                "Values": [expected["endpoint_security_group_id"]],
            }
        ]
    ).get("SecurityGroupRules", [])
    _require(
        isinstance(endpoint_rules, list),
        "The endpoint security group returned an invalid rule inventory.",
    )
    endpoint_rule_projection = {
        (
            rule.get("IsEgress"),
            rule.get("IpProtocol"),
            rule.get("FromPort"),
            rule.get("ToPort"),
            rule.get("CidrIpv4"),
            rule.get("CidrIpv6"),
            rule.get("PrefixListId"),
            (
                rule.get("ReferencedGroupInfo", {}).get("GroupId")
                if isinstance(rule.get("ReferencedGroupInfo"), dict)
                else None
            ),
        )
        for rule in endpoint_rules
    }
    _require(
        endpoint_rule_projection
        == {
            (False, "tcp", 443, 443, None, None, None, security_group_id)
            for security_group_id in endpoint_ingress_security_group_ids
        },
        "The private endpoint security group has broad or unapproved rules.",
    )
    endpoint_ids = [
        cast(dict[str, object], endpoints[name])["id"]
        for name in sorted(required_endpoint_names)
    ]
    live_endpoints = client.describe_vpc_endpoints(
        VpcEndpointIds=endpoint_ids
    ).get("VpcEndpoints", [])
    _require(
        isinstance(live_endpoints, list)
        and {endpoint.get("VpcEndpointId") for endpoint in live_endpoints}
        == set(endpoint_ids),
        "One or more required VPC endpoints could not be described.",
    )
    live_by_id = {endpoint["VpcEndpointId"]: endpoint for endpoint in live_endpoints}
    endpoint_results: dict[str, object] = {}
    for name in sorted(required_endpoint_names):
        endpoint_expected = cast(dict[str, object], endpoints[name])
        endpoint_attachment_keys = (
            {"route_table_ids"}
            if name == "s3"
            else {"subnet_ids", "security_group_ids"}
        )
        _require(
            set(endpoint_expected)
            == {"id", "service_name", "type", "policy_sha256"}
            | endpoint_attachment_keys,
            f"Terraform endpoint {name} has an invalid contract.",
        )
        live = live_by_id[endpoint_expected["id"]]
        expected_type = "Gateway" if name == "s3" else "Interface"
        _require(
            endpoint_expected["service_name"] == f"com.amazonaws.{region}.{name}"
            and endpoint_expected["type"] == expected_type
            and live.get("VpcId") == expected["vpc_id"]
            and live.get("ServiceName") == endpoint_expected["service_name"]
            and live.get("VpcEndpointType") == expected_type
            and live.get("State") == "available"
            and (name == "s3" or live.get("PrivateDnsEnabled") is True)
            and _canonical_policy_digest(live.get("PolicyDocument"))
            == endpoint_expected["policy_sha256"],
            f"Live VPC endpoint {name} does not match its exact Terraform contract.",
        )
        if name == "s3":
            route_table_ids = endpoint_expected["route_table_ids"]
            _require(
                isinstance(route_table_ids, list)
                and route_table_ids == sorted(set(route_table_ids))
                and expected["worker_route_table_id"] in route_table_ids
                and sorted(live.get("RouteTableIds", [])) == route_table_ids,
                "Live S3 gateway endpoint route-table attachments differ from Terraform.",
            )
            attachments: dict[str, object] = {
                "route_table_ids": route_table_ids,
            }
        else:
            endpoint_subnet_ids_value = endpoint_expected["subnet_ids"]
            endpoint_security_group_ids_value = endpoint_expected[
                "security_group_ids"
            ]
            live_groups = live.get("Groups", [])
            live_group_ids = [
                group.get("GroupId")
                for group in live_groups
                if isinstance(group, dict)
                and isinstance(group.get("GroupId"), str)
            ] if isinstance(live_groups, list) else []
            _require(
                isinstance(endpoint_subnet_ids_value, list)
                and all(isinstance(item, str) for item in endpoint_subnet_ids_value)
                and isinstance(endpoint_security_group_ids_value, list)
                and all(
                    isinstance(item, str)
                    for item in endpoint_security_group_ids_value
                ),
                f"Terraform interface endpoint {name} attachments are invalid.",
            )
            endpoint_subnet_ids = cast(list[str], endpoint_subnet_ids_value)
            endpoint_security_group_ids = cast(
                list[str], endpoint_security_group_ids_value
            )
            live_subnet_ids = live.get("SubnetIds", [])
            _require(
                endpoint_subnet_ids == sorted(set(endpoint_subnet_ids))
                and len(endpoint_subnet_ids) >= 2
                and endpoint_security_group_ids
                == [expected["endpoint_security_group_id"]]
                and isinstance(live_subnet_ids, list)
                and all(isinstance(item, str) for item in live_subnet_ids)
                and sorted(cast(list[str], live_subnet_ids)) == endpoint_subnet_ids
                and sorted(cast(list[str], live_group_ids))
                == endpoint_security_group_ids,
                f"Live interface endpoint {name} attachments differ from Terraform.",
            )
            attachments = {
                "subnet_ids": endpoint_subnet_ids,
                "security_group_ids": endpoint_security_group_ids,
            }
        endpoint_results[name] = {
            "id": endpoint_expected["id"],
            "service_name": endpoint_expected["service_name"],
            "type": expected_type,
            "policy_sha256": endpoint_expected["policy_sha256"],
            **attachments,
        }
    return {
        "status": "passed",
        "vpc_id": expected["vpc_id"],
        "worker_security_group_id": expected["worker_security_group_id"],
        "endpoint_security_group_id": expected["endpoint_security_group_id"],
        "worker_subnet_ids": subnet_ids,
        "worker_route_table_id": expected["worker_route_table_id"],
        "allowed_egress_rule_count": len(rule_projection),
        "endpoint_ingress_security_group_ids": endpoint_ingress_security_group_ids,
        "endpoint_ingress_rule_count": len(endpoint_rule_projection),
        "public_or_nat_routes": 0,
        "vpc_endpoints": endpoint_results,
    }


def _list_service_tasks(
    client: Any,
    *,
    cluster: str,
    service: str,
    desired_status: str,
) -> list[str]:
    task_arns: list[str] = []
    next_token: str | None = None
    for _page in range(20):
        request: dict[str, object] = {
            "cluster": cluster,
            "serviceName": service,
            "desiredStatus": desired_status,
        }
        if next_token is not None:
            request["nextToken"] = next_token
        response = client.list_tasks(**request)
        page_arns = response.get("taskArns", [])
        _require(
            isinstance(page_arns, list)
            and all(isinstance(task_arn, str) for task_arn in page_arns),
            f"ECS returned invalid {desired_status} task identifiers for {service}.",
        )
        task_arns.extend(page_arns)
        token = response.get("nextToken")
        if token is None:
            break
        _require(isinstance(token, str) and bool(token), "ECS returned an invalid task cursor.")
        next_token = token
    else:
        raise ReadinessFailure(f"ECS task enumeration exceeded 20 pages for {service}.")
    _require(
        len(task_arns) == len(set(task_arns)),
        f"ECS returned duplicate task identifiers for {service}.",
    )
    return task_arns


def _verify_standalone_task_drain(
    client: Any,
    *,
    cluster: str,
    task_definition_arns: dict[str, str],
    services: dict[str, str | None],
    service_desired_counts: dict[str, int],
    require_successful_migration: bool = False,
) -> dict[str, object]:
    """Prove active inventory and, at activation, the exact successful migration."""

    _require(
        set(task_definition_arns) == {"web", "api", "worker", "migration"}
        and set(services) == set(task_definition_arns),
        "Cluster inventory verification requires all four exact runtime definitions.",
    )
    _require(
        services["migration"] is None
        and set(service_desired_counts)
        == {service for service in services.values() if service is not None},
        "Cluster inventory requires exact approved service desired counts.",
    )
    cluster_tasks: dict[str, list[str]] = {
        desired_status: _list_cluster_tasks(
            client, cluster=cluster, desired_status=desired_status
        )
        for desired_status in ("RUNNING", "STOPPED")
    }
    service_results: dict[str, object] = {}
    running_expectations: dict[str, tuple[str, str, str]] = {}
    stopped_service_owners: dict[str, tuple[str, str]] = {}
    for runtime_name in ("web", "api", "worker"):
        service = services[runtime_name]
        assert isinstance(service, str)
        desired_count = service_desired_counts[service]
        _require(
            type(desired_count) is int and desired_count > 0,
            f"ECS service {service} has an invalid desired inventory.",
        )
        inventories: dict[str, list[str]] = {}
        for desired_status in ("RUNNING", "STOPPED"):
            service_tasks = sorted(
                _list_service_tasks(
                    client,
                    cluster=cluster,
                    service=service,
                    desired_status=desired_status,
                )
            )
            _require(
                set(service_tasks).issubset(cluster_tasks[desired_status]),
                f"ECS returned an inconsistent {service} service task inventory.",
            )
            inventories[desired_status] = service_tasks
            if desired_status == "RUNNING":
                for task_arn in service_tasks:
                    _require(
                        task_arn not in running_expectations
                        and task_arn not in stopped_service_owners,
                        "One ECS task appears in more than one service inventory.",
                    )
                    running_expectations[task_arn] = (
                        runtime_name,
                        service,
                        task_definition_arns[runtime_name],
                    )
            else:
                for task_arn in service_tasks:
                    _require(
                        task_arn not in running_expectations
                        and task_arn not in stopped_service_owners,
                        "One ECS task appears in more than one service inventory.",
                    )
                    stopped_service_owners[task_arn] = (runtime_name, service)
        _require(
            len(inventories["RUNNING"]) == desired_count,
            f"ECS service {service} task inventory does not equal desired count.",
        )
        service_results[runtime_name] = {
            "service": service,
            "task_definition_arn": task_definition_arns[runtime_name],
            "desired_count": desired_count,
            "running_task_arns": inventories["RUNNING"],
            "stopped_task_arns": inventories["STOPPED"],
        }
    _require(
        set(cluster_tasks["RUNNING"]) == set(running_expectations),
        "ECS cluster contains an unapproved standalone, stale, migration, or surplus task.",
    )
    _require(
        set(stopped_service_owners).issubset(cluster_tasks["STOPPED"])
        and set(cluster_tasks["RUNNING"]).isdisjoint(cluster_tasks["STOPPED"]),
        "ECS returned inconsistent running and stopped task inventories.",
    )
    described_tasks: list[dict[str, Any]] = []
    all_task_arns = sorted(
        set(cluster_tasks["RUNNING"]) | set(cluster_tasks["STOPPED"])
    )
    for offset in range(0, len(all_task_arns), 100):
        response = client.describe_tasks(
            cluster=cluster, tasks=all_task_arns[offset : offset + 100]
        )
        _require(not response.get("failures"), "ECS could not describe every cluster task.")
        described = response.get("tasks", [])
        _require(isinstance(described, list), "ECS returned an invalid task inventory.")
        described_tasks.extend(described)
    _require(
        {task.get("taskArn") for task in described_tasks} == set(all_task_arns),
        "ECS did not describe the complete cluster task inventory.",
    )
    stopped_task_history: list[dict[str, object]] = []
    successful_migration_tasks: list[dict[str, object]] = []
    migration_family_arn = task_definition_arns["migration"].rsplit(":", maxsplit=1)[0]
    migration_family_name = migration_family_arn.rsplit("/", maxsplit=1)[-1]
    for task in sorted(described_tasks, key=lambda item: str(item.get("taskArn"))):
        task_arn = str(task["taskArn"])
        containers = task.get("containers")
        _require(
            isinstance(containers, list)
            and len(containers) > 0
            and all(isinstance(container, dict) for container in containers),
            "ECS cluster task has an invalid container inventory.",
        )
        containers = cast(list[dict[str, object]], containers)
        if task_arn in running_expectations:
            runtime_name, expected_service, expected_definition = running_expectations[
                task_arn
            ]
            _require(
                task.get("group") == f"service:{expected_service}"
                and task.get("taskDefinitionArn") == expected_definition
                and task.get("desiredStatus") == "RUNNING"
                and task.get("lastStatus") == "RUNNING"
                and task.get("healthStatus") in {None, "HEALTHY"}
                and len(containers) == 1
                and containers[0].get("name") == runtime_name
                and containers[0].get("lastStatus") == "RUNNING"
                and containers[0].get("healthStatus") in {None, "HEALTHY"},
                "An approved ECS service task is not an exact healthy current task.",
            )
            continue
        _require(
            task.get("desiredStatus") == "STOPPED"
            and task.get("lastStatus") == "STOPPED"
            and all(container.get("lastStatus") == "STOPPED" for container in containers),
            "ECS desired STOPPED history contains a task that is not fully stopped.",
        )
        stopped_at_value = task.get("stoppedAt")
        if isinstance(stopped_at_value, datetime):
            _require(
                stopped_at_value.tzinfo is not None
                and stopped_at_value.utcoffset() is not None,
                "ECS stoppedAt timestamp is invalid.",
            )
            stopped_at = stopped_at_value.astimezone(UTC)
        else:
            stopped_at = _utc_timestamp(stopped_at_value, "ECS stoppedAt timestamp")
        task_definition_arn = task.get("taskDefinitionArn")
        group = task.get("group")
        _require(
            isinstance(task_definition_arn, str) and isinstance(group, str),
            "ECS stopped-task history has missing identity fields.",
        )
        assert isinstance(task_definition_arn, str) and isinstance(group, str)
        owner = stopped_service_owners.get(task_arn)
        if owner is not None:
            stopped_runtime_name, service = owner
            classification = (
                "current-service-revision"
                if task_definition_arn == task_definition_arns[stopped_runtime_name]
                else "prior-service-revision"
            )
        elif (
            task_definition_arn.rsplit(":", maxsplit=1)[0] == migration_family_arn
            or group == f"family:{migration_family_name}"
        ):
            stopped_runtime_name = "migration"
            service = None
            classification = "migration"
        else:
            stopped_runtime_name = None
            service = None
            classification = "other"
        stopped_task_history.append(
            {
                "task_arn": task_arn,
                "runtime": stopped_runtime_name,
                "service": service,
                "classification": classification,
                "group": group,
                "task_definition_arn": task_definition_arn,
                "stopped_at": stopped_at.isoformat().replace("+00:00", "Z"),
            }
        )
        if (
            require_successful_migration
            and classification == "migration"
            and task_definition_arn == task_definition_arns["migration"]
            and group == f"family:{migration_family_name}"
            and len(containers) == 1
            and containers[0].get("name") == "migration"
            and type(containers[0].get("exitCode")) is int
            and containers[0]["exitCode"] == 0
            and task.get("stopCode") == "EssentialContainerExited"
        ):
            successful_migration_tasks.append(
                {
                    "task_arn": task_arn,
                    "task_definition_arn": task_definition_arn,
                    "group": group,
                    "stop_code": task["stopCode"],
                    "container_exit_code": containers[0]["exitCode"],
                    "stopped_at": stopped_at.isoformat().replace("+00:00", "Z"),
                }
            )
    if require_successful_migration:
        _require(
            bool(successful_migration_tasks),
            "No fully stopped successful migration uses the exact pending task definition.",
        )
    return {
        "status": "passed",
        "cluster": cluster,
        "services": service_results,
        "cluster_running_task_arns": sorted(cluster_tasks["RUNNING"]),
        "cluster_stopped_task_history": stopped_task_history,
        "enumerated_desired_statuses": ["RUNNING", "STOPPED"],
        "migration_task_definition_arn": task_definition_arns["migration"],
        "migration_tasks": successful_migration_tasks,
    }


def _simulate_iam_decision(
    client: Any,
    *,
    role_arn: str,
    action: str,
    resource_arn: str,
    context_entries: list[dict[str, object]] | None = None,
) -> str:
    request: dict[str, object] = {
        "PolicySourceArn": role_arn,
        "ActionNames": [action],
        "ResourceArns": [resource_arn],
    }
    if context_entries:
        request["ContextEntries"] = context_entries
    response = client.simulate_principal_policy(**request)
    results = response.get("EvaluationResults", [])
    _require(len(results) == 1, f"IAM simulation returned no unique result for {action}.")
    decision = results[0].get("EvalDecision")
    _require(isinstance(decision, str), f"IAM simulation returned no decision for {action}.")
    assert isinstance(decision, str)
    return decision


def _verify_prior_worker_identity_denials(
    client: Any,
    *,
    prior_role_arns: list[str],
    current_worker_role_arn: str,
    db_user_arn: str,
    bucket_arn: str,
    kms_key_arn: str,
    region: str,
    worker_engagement_id: str,
    bedrock_model_arn: str,
    revocation_evidence: dict[str, object],
    now: datetime | None = None,
) -> dict[str, object]:
    _require(
        prior_role_arns == sorted(set(prior_role_arns)),
        "Prior worker role ARNs must be unique and sorted.",
    )
    object_prefix = f"{bucket_arn}/engagements/{worker_engagement_id}/evidence/*"
    signed_record = revocation_evidence.get("signed_record")
    _require(
        isinstance(signed_record, dict),
        "Prior worker session revocation evidence is not a signed envelope.",
    )
    signed_record = cast(dict[str, object], signed_record)
    current_release_revision = signed_record.get("release_revision")
    current_deployment_id = signed_record.get("deployment_id")
    _require(
        isinstance(current_release_revision, str)
        and isinstance(current_deployment_id, str),
        "Prior worker session revocation evidence has no release identity.",
    )
    assert isinstance(current_release_revision, str)
    assert isinstance(current_deployment_id, str)
    evidence_results = signed_record.get("results")
    evidence_roles_value = (
        evidence_results.get("roles") if isinstance(evidence_results, dict) else None
    )
    _require(
        isinstance(evidence_roles_value, list),
        "Prior worker session revocation evidence has no exact role list.",
    )
    evidence_roles_value = cast(list[object], evidence_roles_value)
    evidence_roles = {
        str(role.get("role_arn")): role
        for role in evidence_roles_value
        if isinstance(role, dict)
    }
    _require(
        sorted(evidence_roles) == prior_role_arns
        and len(evidence_roles) == len(evidence_roles_value),
        "Signed prior-worker revocation evidence does not match the explicit prior-role set.",
    )
    kms_context: list[dict[str, object]] = [
        {
            "ContextKeyName": "kms:ViaService",
            "ContextKeyValues": [f"s3.{region}.amazonaws.com"],
            "ContextKeyType": "string",
        },
        {
            "ContextKeyName": "kms:EncryptionContext:aws:s3:arn",
            "ContextKeyValues": [bucket_arn],
            "ContextKeyType": "string",
        },
    ]
    roles: list[dict[str, object]] = []
    reference_time = (now or datetime.now(UTC)).astimezone(UTC)
    for role_arn in prior_role_arns:
        _require(
            _IAM_ROLE_ARN_PATTERN.fullmatch(role_arn) is not None
            and "*" not in role_arn
            and role_arn != current_worker_role_arn,
            "Each prior worker identity must be one exact non-current IAM role ARN.",
        )
        evidence_role = evidence_roles[role_arn]
        _require(
            isinstance(evidence_role, dict),
            "Signed prior-worker role evidence is malformed.",
        )
        evidence_role = cast(dict[str, object], evidence_role)
        targets = evidence_role.get("targets")
        probes = evidence_role.get("probe_results")
        _require(
            isinstance(targets, dict)
            and targets
            == {
                "db_user_arn": db_user_arn,
                "s3_object_prefix_arn": object_prefix,
                "kms_key_arn": kms_key_arn,
                "bedrock_model_arn": bedrock_model_arn,
            }
            and isinstance(probes, dict)
            and all(value == "denied" for value in probes.values()),
            "Signed prior-worker probes are not bound to the current exact resources.",
        )
        role_name = role_arn.rsplit("/", maxsplit=1)[-1]
        identity_state = evidence_role.get("identity_state")
        live_quarantine: dict[str, object] | None
        if identity_state == "retained-quarantined":
            probe_completed_at = _utc_timestamp(
                evidence_role.get("live_probe_completed_at"),
                "Prior-worker live probe timestamp",
            )
            _require(
                reference_time - timedelta(seconds=DEFAULT_MAXIMUM_PROBE_AGE_SECONDS)
                <= probe_completed_at
                <= reference_time,
                "Signed prior-worker live denied probes are no longer current.",
            )
            try:
                live_quarantine = verify_live_prior_worker_quarantine(
                    client,
                    role_arn=role_arn,
                    prior_release_revision=str(evidence_role["prior_release_revision"]),
                    prior_deployment_id=str(evidence_role["prior_deployment_id"]),
                    current_release_revision=current_release_revision,
                    current_deployment_id=current_deployment_id,
                    expected_policy_digest=str(
                        evidence_role["quarantine_policy_digest"]
                    ),
                    expected_cutoff_at=str(evidence_role["revocation_cutoff_at"]),
                    expected_max_session_duration=cast(
                        int, evidence_role["max_session_duration_seconds"]
                    ),
                )
            except (KeyError, PriorWorkerRoleError) as error:
                raise ReadinessFailure(
                    f"IAM live quarantine state is invalid for {role_arn}."
                ) from error
            iam_role_state = "present"
            decisions = {
                "rds_db_connect": _simulate_iam_decision(
                    client,
                    role_arn=role_arn,
                    action="rds-db:connect",
                    resource_arn=db_user_arn,
                ),
                "s3_get_current_prefix": _simulate_iam_decision(
                    client,
                    role_arn=role_arn,
                    action="s3:GetObject",
                    resource_arn=object_prefix,
                ),
                "s3_put_current_prefix": _simulate_iam_decision(
                    client,
                    role_arn=role_arn,
                    action="s3:PutObject",
                    resource_arn=object_prefix,
                ),
                "kms_decrypt_current_key": _simulate_iam_decision(
                    client,
                    role_arn=role_arn,
                    action="kms:Decrypt",
                    resource_arn=kms_key_arn,
                    context_entries=kms_context,
                ),
                "kms_generate_data_key_current_key": _simulate_iam_decision(
                    client,
                    role_arn=role_arn,
                    action="kms:GenerateDataKey",
                    resource_arn=kms_key_arn,
                    context_entries=kms_context,
                ),
                "bedrock_invoke_current_model": _simulate_iam_decision(
                    client,
                    role_arn=role_arn,
                    action="bedrock:InvokeModel",
                    resource_arn=bedrock_model_arn,
                ),
            }
        elif identity_state == "deleted-after-ttl":
            try:
                client.get_role(RoleName=role_name)
            except ClientError as error:
                error_code = error.response.get("Error", {}).get("Code")
                if error_code not in {"NoSuchEntity", "NoSuchEntityException"}:
                    raise ReadinessFailure(
                        f"IAM could not prove prior worker role state for {role_arn}."
                    ) from error
            else:
                raise ReadinessFailure(
                    "Signed prior-worker evidence claims deletion, but the role exists."
                )
            decisions = {key: "denied" for key in cast(dict[str, object], probes)}
            iam_role_state = "NoSuchEntity"
            live_quarantine = None
        else:
            raise ReadinessFailure("Signed prior-worker lifecycle state is invalid.")
        normalized = {
            key: ("denied" if value != "allowed" else "allowed")
            for key, value in decisions.items()
        }
        _require(
            all(value == "denied" for value in normalized.values()),
            f"Prior worker role {role_arn} retains current deployment authority.",
        )
        roles.append(
            {
                "role_arn": role_arn,
                "identity_state": evidence_role["identity_state"],
                "iam_get_role": iam_role_state,
                "revocation_cutoff_at": evidence_role["revocation_cutoff_at"],
                "live_probe_completed_at": evidence_role["live_probe_completed_at"],
                "deleted_at": evidence_role["deleted_at"],
                "live_quarantine": live_quarantine,
                **normalized,
            }
        )
    return {
        "status": "passed",
        "first_deployment": not prior_role_arns,
        "revocation_evidence_content_digest": revocation_evidence["content_digest"],
        "roles": roles,
    }


def _verify_worker_s3_isolation(
    client: Any,
    *,
    role_arn: str,
    bucket_arn: str,
    kms_key_arn: str,
    region: str,
    worker_engagement_id: str,
) -> dict[str, object]:
    engagement = uuid.UUID(worker_engagement_id)
    other_engagement = uuid.UUID(int=1 if engagement.int != 1 else 2)
    own_object = f"{bucket_arn}/engagements/{engagement}/evidence/readiness-probe"
    other_object = (
        f"{bucket_arn}/engagements/{other_engagement}/evidence/readiness-probe"
    )
    object_decisions = {
        "assigned_prefix_get_object": _simulate_iam_decision(
            client,
            role_arn=role_arn,
            action="s3:GetObject",
            resource_arn=own_object,
        ),
        "assigned_prefix_get_object_version": _simulate_iam_decision(
            client,
            role_arn=role_arn,
            action="s3:GetObjectVersion",
            resource_arn=own_object,
        ),
        "cross_engagement_get_object": _simulate_iam_decision(
            client,
            role_arn=role_arn,
            action="s3:GetObject",
            resource_arn=other_object,
        ),
        "cross_engagement_get_object_version": _simulate_iam_decision(
            client,
            role_arn=role_arn,
            action="s3:GetObjectVersion",
            resource_arn=other_object,
        ),
        "assigned_prefix_put_object": _simulate_iam_decision(
            client,
            role_arn=role_arn,
            action="s3:PutObject",
            resource_arn=own_object,
        ),
        "assigned_prefix_delete_object": _simulate_iam_decision(
            client,
            role_arn=role_arn,
            action="s3:DeleteObject",
            resource_arn=own_object,
        ),
        "assigned_prefix_delete_object_version": _simulate_iam_decision(
            client,
            role_arn=role_arn,
            action="s3:DeleteObjectVersion",
            resource_arn=own_object,
        ),
    }
    list_decision = _simulate_iam_decision(
        client,
        role_arn=role_arn,
        action="s3:ListBucket",
        resource_arn=bucket_arn,
    )
    location_decision = _simulate_iam_decision(
        client,
        role_arn=role_arn,
        action="s3:GetBucketLocation",
        resource_arn=bucket_arn,
    )
    via_s3_context: list[dict[str, object]] = [
        {
            "ContextKeyName": "kms:ViaService",
            "ContextKeyValues": [f"s3.{region}.amazonaws.com"],
            "ContextKeyType": "string",
        },
        {
            "ContextKeyName": "kms:EncryptionContext:aws:s3:arn",
            "ContextKeyValues": [bucket_arn],
            "ContextKeyType": "string",
        },
    ]
    kms_via_s3_decision = _simulate_iam_decision(
        client,
        role_arn=role_arn,
        action="kms:Decrypt",
        resource_arn=kms_key_arn,
        context_entries=via_s3_context,
    )
    kms_direct_decision = _simulate_iam_decision(
        client,
        role_arn=role_arn,
        action="kms:Decrypt",
        resource_arn=kms_key_arn,
    )
    _require(
        object_decisions["assigned_prefix_get_object"] == "allowed"
        and object_decisions["assigned_prefix_get_object_version"] == "allowed",
        "Worker cannot read current and versioned objects in its assigned evidence prefix.",
    )
    _require(
        object_decisions["cross_engagement_get_object"] != "allowed"
        and object_decisions["cross_engagement_get_object_version"] != "allowed",
        "Worker can read current or versioned evidence from a different engagement.",
    )
    _require(
        all(
            object_decisions[name] != "allowed"
            for name in {
                "assigned_prefix_put_object",
                "assigned_prefix_delete_object",
                "assigned_prefix_delete_object_version",
            }
        ),
        "Worker can mutate current or versioned objects in its assigned evidence prefix.",
    )
    _require(list_decision != "allowed", "Worker can enumerate the evidence bucket.")
    _require(
        location_decision != "allowed",
        "Worker retains unnecessary bucket-location authority.",
    )
    _require(
        kms_via_s3_decision == "allowed",
        "Worker cannot decrypt assigned evidence through S3.",
    )
    _require(kms_direct_decision != "allowed", "Worker can invoke KMS decrypt outside S3.")
    return {
        "status": "passed",
        "worker_engagement_id": worker_engagement_id,
        **{
            name: ("allowed" if decision == "allowed" else "denied")
            for name, decision in object_decisions.items()
        },
        "list_bucket": "denied",
        "get_bucket_location": "denied",
        "kms_decrypt_via_s3": "allowed",
        "kms_decrypt_direct": "denied",
    }


def _verify_worker_bedrock_isolation(
    client: Any,
    *,
    role_arn: str,
    model_arn: str,
) -> dict[str, object]:
    arn_prefix, model_resource = model_arn.rsplit("/", maxsplit=1)
    alternate_model_arn = f"{arn_prefix}/{model_resource}-qualification-denied-probe"
    _arn, partition, _service, configured_region, _account, _resource = model_arn.split(
        ":", maxsplit=5
    )
    alternate_region = "us-east-1" if configured_region != "us-east-1" else "us-west-2"
    alternate_region_arn = model_arn.replace(
        f"{partition}:bedrock:{configured_region}:",
        f"{partition}:bedrock:{alternate_region}:",
        1,
    )
    configured_decision = _simulate_iam_decision(
        client,
        role_arn=role_arn,
        action="bedrock:InvokeModel",
        resource_arn=model_arn,
    )
    alternate_decision = _simulate_iam_decision(
        client,
        role_arn=role_arn,
        action="bedrock:InvokeModel",
        resource_arn=alternate_model_arn,
    )
    alternate_region_decision = _simulate_iam_decision(
        client,
        role_arn=role_arn,
        action="bedrock:InvokeModel",
        resource_arn=alternate_region_arn,
    )
    _require(
        configured_decision == "allowed",
        "Worker cannot invoke the configured Bedrock model ARN.",
    )
    _require(
        alternate_decision != "allowed" and alternate_region_decision != "allowed",
        "Worker can invoke a Bedrock model outside the configured ARN or region.",
    )
    return {
        "status": "passed",
        "configured_model_arn": model_arn,
        "configured_model_invoke": "allowed",
        "alternate_model_invoke": "denied",
        "alternate_region_model_invoke": "denied",
    }


def _verify_worker_database_identity(
    client: Any,
    *,
    task_role_arns: dict[str, str],
    expected_worker_role_arn: str,
    db_user_arn: str,
) -> dict[str, object]:
    """Require only this deployment's worker task role to authenticate as the worker."""

    worker_role_arn = task_role_arns.get("worker")
    _require(
        worker_role_arn == expected_worker_role_arn,
        "The live worker does not use this deployment's exact workload role.",
    )
    decisions = {
        runtime_name: _simulate_iam_decision(
            client,
            role_arn=role_arn,
            action="rds-db:connect",
            resource_arn=db_user_arn,
        )
        for runtime_name, role_arn in task_role_arns.items()
    }
    _require(
        decisions.get("worker") == "allowed",
        "The release-scoped worker role cannot authenticate to RDS.",
    )
    _require(
        all(
            decision != "allowed"
            for runtime_name, decision in decisions.items()
            if runtime_name != "worker"
        ),
        "A non-worker runtime can authenticate as the database worker.",
    )
    return {
        "status": "passed",
        "worker_role_arn": worker_role_arn,
        "db_user_arn": db_user_arn,
        "worker_connect": "allowed",
        "non_worker_connect": "denied",
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
        "The configured regional Bedrock foundation model was not evaluated by the supplied job.",
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
        re.fullmatch(r"[0-9a-f]{40}", args.git_commit) is not None and args.git_commit != "0" * 40,
        "The release Git commit must be a non-placeholder exact 40-character lowercase SHA.",
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
    _require(
        re.fullmatch(r"[a-z0-9][a-z0-9._-]{7,119}", args.deployment_id) is not None,
        "The deployment ID must be a bounded stable identifier.",
    )
    _require(
        args.qualification_mode == "controlled-design-partner",
        "The readiness gate only accepts controlled-design-partner qualification mode.",
    )
    _require(
        _IAM_ROLE_ARN_PATTERN.fullmatch(args.evidence_issuer_role_arn) is not None
        and "*" not in args.evidence_issuer_role_arn,
        "The evidence issuer must be one exact IAM role ARN.",
    )
    signing_key_pattern = re.compile(
        r"arn:aws(?:-us-gov|-cn|-iso|-iso-b)?:kms:[a-z0-9-]+:[0-9]{12}:"
        r"key/[0-9a-fA-F-]{32,64}"
    )
    _require(
        signing_key_pattern.fullmatch(args.evidence_signing_key_arn) is not None
        and "*" not in args.evidence_signing_key_arn,
        "The evidence signing key must be one exact KMS key ARN.",
    )
    prior_roles = args.prior_worker_task_role_arn or []
    explicit_first_deployment = bool(
        getattr(args, "no_prior_worker_task_roles", False)
    )
    _require(
        explicit_first_deployment == (not prior_roles)
        and prior_roles == sorted(set(prior_roles))
        and all(
            _IAM_ROLE_ARN_PATTERN.fullmatch(role_arn) is not None
            and "*" not in role_arn
            and role_arn != args.worker_task_role_arn
            for role_arn in prior_roles
        ),
        "Supply sorted unique prior worker roles, or explicitly declare a first deployment.",
    )
    _require(
        1 <= args.max_external_evidence_age_days <= 90,
        "The external evidence age window must be between 1 and 90 days.",
    )
    _require(
        5 <= args.max_rpo_minutes <= 60,
        "The RDS RPO gate must remain between 5 and 60 minutes.",
    )
    _require(
        1 <= args.max_secret_age_days <= 90,
        "The runtime secret age window must be between 1 and 90 days.",
    )
    _require(
        1 <= args.qualification_validity_hours <= 720,
        "The qualification validity window must be between 1 hour and 30 days.",
    )
    application_url = urlsplit(args.application_url)
    _require(
        application_url.scheme == "https"
        and application_url.hostname is not None
        and application_url.netloc == application_url.hostname
        and application_url.username is None
        and application_url.password is None
        and application_url.path == ""
        and not application_url.query
        and not application_url.fragment
        and args.application_url == f"https://{application_url.hostname}",
        "The application URL must be one canonical credential-free HTTPS origin.",
    )
    issuer_url = urlsplit(args.oidc_issuer_url)
    _require(
        issuer_url.scheme == "https"
        and issuer_url.hostname is not None
        and issuer_url.netloc == issuer_url.hostname
        and issuer_url.username is None
        and issuer_url.password is None
        and issuer_url.path.startswith("/")
        and issuer_url.path.endswith("/")
        and not issuer_url.query
        and not issuer_url.fragment
        and args.oidc_issuer_url
        == f"https://{issuer_url.hostname}{issuer_url.path}",
        "The OIDC issuer URL must be canonical credential-free HTTPS with a trailing slash.",
    )
    _require(
        re.fullmatch(r"[A-Za-z0-9._~-]{3,255}", args.oidc_client_id) is not None,
        "The OIDC client ID must be a bounded canonical identifier.",
    )
    _require(
        bool(args.oidc_allowed_email)
        and len(args.oidc_allowed_email) <= 100
        and args.oidc_allowed_email == sorted(set(args.oidc_allowed_email))
        and all(
            email == email.casefold()
            and re.fullmatch(
                r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,63}",
                email,
            )
            is not None
            for email in args.oidc_allowed_email
        ),
        "OIDC allowed emails must be nonempty, canonical, unique, and sorted.",
    )
    try:
        worker_operator = uuid.UUID(args.worker_operator_id)
        worker_engagement = uuid.UUID(args.worker_engagement_id)
    except (AttributeError, ValueError) as error:
        raise ReadinessFailure("The worker identity values must be canonical UUIDs.") from error
    _require(
        worker_operator.int != 0 and str(worker_operator) == args.worker_operator_id,
        "The worker operator ID must be a nonzero canonical lowercase UUID.",
    )
    _require(
        worker_engagement.int != 0 and str(worker_engagement) == args.worker_engagement_id,
        "The worker engagement ID must be a nonzero canonical lowercase UUID.",
    )
    concrete_bedrock_arn = re.compile(
        r"^arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):bedrock:([a-z0-9-]{1,20}):"
        r":foundation-model/([A-Za-z0-9:.-]+)$"
    )
    bedrock_arn_match = concrete_bedrock_arn.fullmatch(args.bedrock_model_arn)
    _require(
        bedrock_arn_match is not None
        and bedrock_arn_match.group(2) == args.region
        and "*" not in args.bedrock_model_arn,
        "The Bedrock model ARN must be one exact regional accountless foundation-model ARN.",
    )
    assert bedrock_arn_match is not None
    model_resource_id = bedrock_arn_match.group(3)
    _require(
        args.bedrock_model_id == model_resource_id,
        "The Bedrock runtime model ID does not match the exact authorized model ARN.",
    )
    classifications = args.bedrock_allowed_data_classification or ["PUBLIC", "INTERNAL"]
    _require(
        bool(classifications)
        and len(classifications) == len(set(classifications))
        and set(classifications) <= {"PUBLIC", "INTERNAL", "CONFIDENTIAL"},
        "Bedrock classifications must be unique supported values; RESTRICTED is never allowed.",
    )
    return {
        "git_commit": args.git_commit,
        "deployment_id": args.deployment_id,
        "qualification_mode": args.qualification_mode,
        "worker_operator_id": str(worker_operator),
        "worker_engagement_id": str(worker_engagement),
        "worker_database_user": worker_database_user_for_release(
            args.deployment_id, args.git_commit
        ),
        "application_origin": args.application_url,
        "oidc_issuer_url": args.oidc_issuer_url,
        "oidc_client_id": args.oidc_client_id,
        "oidc_allowed_emails": list(args.oidc_allowed_email),
        "evidence_issuer_role_arn": args.evidence_issuer_role_arn,
        "evidence_signing_key_arn": args.evidence_signing_key_arn,
        "bedrock_model_id": args.bedrock_model_id,
        "bedrock_model_arn": args.bedrock_model_arn,
        "bedrock_allowed_data_classifications": sorted(classifications),
        "images": images,
    }


def _verify_evidence_signing_public_key(
    client: Any,
    *,
    signing_key_arn: str,
) -> dict[str, str]:
    try:
        response = client.get_public_key(KeyId=signing_key_arn)
    except ClientError as error:
        raise ReadinessFailure("AWS KMS did not return the evidence public key.") from error
    public_key = response.get("PublicKey")
    _require(
        response.get("KeyId") == signing_key_arn
        and response.get("KeyUsage") == "SIGN_VERIFY"
        and response.get("KeySpec") == "RSA_3072"
        and "RSASSA_PSS_SHA_256" in response.get("SigningAlgorithms", [])
        and isinstance(public_key, bytes)
        and 384 <= len(public_key) <= 1024,
        "The evidence KMS key is not the exact supported RSA_3072 signing key.",
    )
    assert isinstance(public_key, bytes)
    encoded = base64.b64encode(public_key).decode("ascii")
    return {
        "evidence_signing_public_key_der_b64": encoded,
        "evidence_signing_public_key_b64_sha256": (
            "sha256:" + hashlib.sha256(encoded.encode("ascii")).hexdigest()
        ),
    }


def _external_evidence(args: argparse.Namespace, *, kms_client: Any) -> dict[str, object]:
    records: dict[str, object] = {}
    for label, path, evidence_type in (
        ("auth0", args.auth0_validation_record, "auth0-live-validation"),
        ("restore", args.restore_rehearsal_record, "isolated-restore-rehearsal"),
        ("deletion", args.deletion_rehearsal_record, "deletion-boundary-rehearsal"),
        ("secret_rotation", args.secret_rotation_record, "runtime-secret-rotation"),
        (
            "prior_worker_revocation",
            args.prior_worker_revocation_record,
            "prior-worker-session-revocation",
        ),
    ):
        try:
            records[label] = load_and_validate_evidence_record(
                path,
                expected_type=evidence_type,
                expected_revision=args.git_commit,
                expected_deployment_id=args.deployment_id,
                expected_issuer_role_arn=args.evidence_issuer_role_arn,
                expected_signing_key_arn=args.evidence_signing_key_arn,
                kms_client=kms_client,
                maximum_age_days=args.max_external_evidence_age_days,
            )
        except EvidenceRecordError as error:
            raise ReadinessFailure(
                f"The {label} external evidence record failed: {error}"
            ) from error
    return records


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


def _verify_secret(
    client: Any,
    secret_id: str,
    max_age_days: int,
    *,
    expected_current_version_id: str,
    now: datetime | None = None,
) -> dict[str, object]:
    secret = client.describe_secret(SecretId=secret_id)
    _require(secret.get("DeletedDate") is None, "A runtime secret is scheduled for deletion.")
    changed_at = secret.get("LastChangedDate") or secret["CreatedDate"]
    _require(
        isinstance(changed_at, datetime)
        and changed_at.tzinfo is not None
        and changed_at.utcoffset() is not None,
        "A runtime secret has no valid change timestamp.",
    )
    assert isinstance(changed_at, datetime)
    _require(
        changed_at >= (now or datetime.now(UTC)) - timedelta(days=max_age_days),
        f"The runtime secret is older than {max_age_days} days.",
    )
    versions: list[dict[str, object]] = []
    next_token: str | None = None
    for _page in range(20):
        request: dict[str, object] = {
            "SecretId": secret_id,
            "IncludeDeprecated": True,
        }
        if next_token is not None:
            request["NextToken"] = next_token
        response = client.list_secret_version_ids(**request)
        page_versions = response.get("Versions", [])
        _require(
            isinstance(page_versions, list)
            and all(isinstance(version, dict) for version in page_versions),
            "Secrets Manager returned an invalid version inventory.",
        )
        versions.extend(cast(list[dict[str, object]], page_versions))
        token = response.get("NextToken")
        if token is None:
            break
        _require(
            isinstance(token, str) and bool(token),
            "Secrets Manager returned an invalid version cursor.",
        )
        next_token = token
    else:
        raise ReadinessFailure("Runtime secret version enumeration exceeded 20 pages.")
    version_ids = [version.get("VersionId") for version in versions]
    _require(
        bool(versions)
        and all(
            isinstance(version_id, str)
            and re.fullmatch(r"[A-Za-z0-9-]{32,64}", version_id) is not None
            for version_id in version_ids
        )
        and len(version_ids) == len(set(version_ids)),
        "Secrets Manager returned duplicate or invalid version identifiers.",
    )
    current_versions: list[dict[str, object]] = []
    for version in versions:
        stages = version.get("VersionStages", [])
        _require(
            isinstance(stages, list)
            and all(isinstance(stage, str) for stage in stages),
            "Secrets Manager returned invalid version stages.",
        )
        assert isinstance(stages, list)
        if "AWSCURRENT" in cast(list[str], stages):
            current_versions.append(version)
    _require(
        len(current_versions) == 1,
        "A runtime secret must have exactly one AWSCURRENT version.",
    )
    current = current_versions[0]
    current_version_id = current.get("VersionId")
    current_created_at = current.get("CreatedDate")
    _require(
        current_version_id == expected_current_version_id,
        "A runtime secret AWSCURRENT version does not match signed rotation evidence.",
    )
    _require(
        isinstance(current_created_at, datetime)
        and current_created_at.tzinfo is not None
        and current_created_at.utcoffset() is not None,
        "The AWSCURRENT runtime secret has no valid creation timestamp.",
    )
    assert isinstance(current_version_id, str)
    assert isinstance(current_created_at, datetime)
    return {
        "status": "passed",
        "secret_arn": secret["ARN"],
        "last_changed": changed_at.astimezone(UTC).isoformat(),
        "maximum_age_days": max_age_days,
        "current_version_id": current_version_id,
        "current_version_created_at": current_created_at.astimezone(UTC).isoformat(),
        "awscurrent_count": 1,
        "observed_version_count": len(versions),
    }


def _bind_runtime_secrets_to_ecs(
    runtime_secrets: dict[str, dict[str, object]],
    ecs_check: dict[str, object],
) -> dict[str, dict[str, object]]:
    registrations_value = ecs_check.get("task_definition_registered_at")
    _require(
        isinstance(registrations_value, dict),
        "ECS proof has no task-definition registration times.",
    )
    registrations = cast(dict[str, object], registrations_value)
    selectors_value = ecs_check.get("runtime_secret_value_from")
    _require(
        isinstance(selectors_value, dict)
        and set(selectors_value) == {"api", "migration"},
        "ECS proof has no exact runtime-secret selector inventory.",
    )
    selectors = cast(dict[str, object], selectors_value)
    _require(
        set(runtime_secrets) == {"api", "migration"},
        "Runtime secret proof must contain exactly API and migration.",
    )
    bound: dict[str, dict[str, object]] = {}
    for runtime_name, secret in runtime_secrets.items():
        registered_at = _utc_timestamp(
            registrations.get(runtime_name),
            f"{runtime_name} task-definition registration",
        )
        current_created_at = _utc_timestamp(
            secret.get("current_version_created_at"),
            f"{runtime_name} AWSCURRENT creation",
        )
        _require(
            current_created_at <= registered_at,
            f"The {runtime_name} task definition predates its bound AWSCURRENT secret version.",
        )
        runtime_selectors = selectors.get(runtime_name)
        _require(
            isinstance(runtime_selectors, dict)
            and all(
                isinstance(name, str) and isinstance(value, str)
                for name, value in runtime_selectors.items()
            ),
            f"The {runtime_name} task definition has no exact secret selector map.",
        )
        bound[runtime_name] = {
            **secret,
            "task_definition_registered_at": registered_at.isoformat(),
            "ecs_value_from": runtime_selectors,
        }
    return bound


def _verify_qualification_secret_boundary(
    client: Any,
    *,
    secret_arn: str,
    qualifier_role_arn: str,
    expected_policy_sha256: str,
) -> dict[str, object]:
    response = client.get_resource_policy(SecretId=secret_arn)
    try:
        policy = json.loads(response["ResourcePolicy"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ReadinessFailure("The qualification secret has no valid resource policy.") from error
    expected_policy = {
        "Version": "2012-10-17",
        "Statement": [
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
                "Resource": secret_arn,
                "Condition": {
                    "ArnNotEquals": {"aws:PrincipalArn": qualifier_role_arn}
                },
            }
        ],
    }
    policy_sha256 = _canonical_policy_digest(policy)
    _require(
        policy == expected_policy and policy_sha256 == expected_policy_sha256,
        "The qualification secret resource policy differs from its exact Terraform contract.",
    )
    return {
        "status": "passed",
        "secret_arn": secret_arn,
        "only_writer_role_arn": qualifier_role_arn,
        "policy_sha256": policy_sha256,
    }


def _verify_qualifier_identity(
    identity: dict[str, Any],
    *,
    qualifier_role_arn: str,
    deployment_role_arn: str,
) -> None:
    _require(
        qualifier_role_arn != deployment_role_arn,
        "The qualifier and deployment roles must be separate principals.",
    )
    role_match = re.fullmatch(
        r"arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):iam::([0-9]{12}):role/(.+)",
        qualifier_role_arn,
    )
    principal_match = re.fullmatch(
        r"arn:(aws(?:-us-gov|-cn|-iso|-iso-b)?):sts::([0-9]{12}):assumed-role/(.+)/([^/]+)",
        str(identity.get("Arn", "")),
    )
    _require(
        role_match is not None
        and principal_match is not None
        and role_match.group(1) == principal_match.group(1)
        and role_match.group(2) == principal_match.group(2)
        and role_match.group(3) == principal_match.group(3),
        "The readiness verifier must run as the dedicated qualifier role.",
    )
    assert role_match is not None
    _require(
        identity.get("Account") == role_match.group(2),
        "The qualifier role is not in the verified AWS account.",
    )


def _publish_qualification_record(
    client: Any,
    *,
    secret_id: str,
    record: dict[str, Any],
) -> str:
    secret = client.describe_secret(SecretId=secret_id)
    _require(secret.get("DeletedDate") is None, "The qualification secret is being deleted.")
    validation_id = str(record["validation_id"])
    version_id = validation_id.removeprefix("sha256:")
    serialized = json.dumps(record, sort_keys=True, separators=(",", ":"))
    _require(
        0 < len(serialized.encode("utf-8")) <= MAX_QUALIFICATION_RECORD_BYTES,
        "The qualification record exceeds the Secrets Manager 64 KiB payload ceiling.",
    )
    response = client.put_secret_value(
        SecretId=secret["ARN"],
        ClientRequestToken=version_id,
        SecretString=serialized,
    )
    _require(
        response.get("VersionId") == version_id,
        "Secrets Manager did not preserve the derived qualification version ID.",
    )
    return version_id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed AWS and external-evidence gate for sanitized design-partner data."
    )
    parser.add_argument("--region", required=True)
    parser.add_argument("--application-url", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--evidence-kms-key-arn", required=True)
    parser.add_argument("--evidence-bucket-policy-sha256", required=True)
    parser.add_argument("--db-instance", required=True)
    parser.add_argument(
        "--rds-boundary",
        type=Path,
        required=True,
        help="Raw JSON from `terraform output -json rds_boundary`.",
    )
    parser.add_argument("--cluster", required=True)
    parser.add_argument(
        "--ecs-role-boundary",
        type=Path,
        required=True,
        help="Raw JSON from `terraform output -json ecs_role_boundary`.",
    )
    parser.add_argument("--web-service", default="web")
    parser.add_argument("--api-service", default="api")
    parser.add_argument("--worker-service", default="worker")
    parser.add_argument("--migration-task-definition-arn", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument(
        "--qualification-mode",
        default="controlled-design-partner",
        choices=["controlled-design-partner"],
    )
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--worker-image", required=True)
    parser.add_argument("--worker-operator-id", required=True)
    parser.add_argument("--worker-engagement-id", required=True)
    parser.add_argument("--bedrock-evaluation-job", required=True)
    parser.add_argument("--bedrock-model-id", required=True)
    parser.add_argument("--bedrock-model-arn", required=True)
    parser.add_argument(
        "--bedrock-allowed-data-classification",
        action="append",
        choices=["PUBLIC", "INTERNAL", "CONFIDENTIAL"],
        help="Repeat to supply the exact runtime list; defaults to PUBLIC and INTERNAL.",
    )
    parser.add_argument("--api-secret", required=True)
    parser.add_argument("--migration-secret", required=True)
    parser.add_argument("--qualification-secret", required=True)
    parser.add_argument("--qualification-secret-policy-sha256", required=True)
    parser.add_argument(
        "--qualification-control-boundary",
        type=Path,
        required=True,
        help="Raw JSON from `terraform output -json qualification_control_boundary`.",
    )
    parser.add_argument("--qualifier-role-arn", required=True)
    parser.add_argument("--deployment-role-arn", required=True)
    parser.add_argument("--worker-task-role-arn", required=True)
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
    parser.add_argument("--evidence-issuer-role-arn", required=True)
    parser.add_argument("--evidence-signing-key-arn", required=True)
    parser.add_argument("--oidc-issuer-url", required=True)
    parser.add_argument("--oidc-client-id", required=True)
    parser.add_argument("--oidc-allowed-email", action="append", required=True)
    parser.add_argument("--qualification-validity-hours", type=int, default=24)
    parser.add_argument("--max-secret-age-days", type=int, default=90)
    parser.add_argument("--max-rpo-minutes", type=int, default=15)
    parser.add_argument("--max-external-evidence-age-days", type=int, default=30)
    parser.add_argument("--auth0-validation-record", type=Path, required=True)
    parser.add_argument("--restore-rehearsal-record", type=Path, required=True)
    parser.add_argument("--deletion-rehearsal-record", type=Path, required=True)
    parser.add_argument("--secret-rotation-record", type=Path, required=True)
    parser.add_argument("--prior-worker-revocation-record", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.output and args.output.exists():
        raise ReadinessFailure(
            "The readiness output already exists; refusing to overwrite qualification evidence."
        )
    session = boto3.Session(region_name=args.region)
    identity = session.client("sts").get_caller_identity()
    _verify_qualifier_identity(
        identity,
        qualifier_role_arn=args.qualifier_role_arn,
        deployment_role_arn=args.deployment_role_arn,
    )
    release = _release_inputs(args)
    worker_network_boundary = _load_worker_network_boundary(
        args.worker_network_boundary
    )
    rds_boundary = _load_rds_boundary(args.rds_boundary)
    qualification_control_boundary = _load_qualification_control_boundary(
        args.qualification_control_boundary
    )
    ecs_role_boundary = _load_ecs_role_boundary(args.ecs_role_boundary)
    task_role_values = ecs_role_boundary.get("task_role_arns")
    execution_role_values = ecs_role_boundary.get("execution_role_arns")
    _require(
        isinstance(task_role_values, dict)
        and isinstance(execution_role_values, dict),
        "The Terraform ECS role boundary has no role maps.",
    )
    task_role_arns = cast(dict[str, str], task_role_values)
    execution_role_arns = cast(dict[str, str], execution_role_values)
    release.update(
        {
            "task_role_arns": task_role_arns,
            "execution_role_arns": execution_role_arns,
        }
    )
    kms_client = session.client("kms")
    release.update(
        _verify_evidence_signing_public_key(
            kms_client,
            signing_key_arn=args.evidence_signing_key_arn,
        )
    )
    external_evidence = _external_evidence(args, kms_client=kms_client)
    rotation_summary = cast(dict[str, object], external_evidence["secret_rotation"])
    rotation_envelope = rotation_summary.get("signed_record")
    _require(
        isinstance(rotation_envelope, dict),
        "Runtime rotation evidence has no signed envelope.",
    )
    assert isinstance(rotation_envelope, dict)
    rotation_results_value = rotation_envelope.get("results")
    _require(
        isinstance(rotation_results_value, dict),
        "Runtime rotation evidence has no typed results.",
    )
    rotation_results = cast(dict[str, object], rotation_results_value)
    secrets_client = session.client("secretsmanager")
    runtime_secrets = {
        role: _verify_secret(
            secrets_client,
            secret_id,
            args.max_secret_age_days,
            expected_current_version_id=str(
                rotation_results[f"{role}_current_version_id"]
            ),
        )
        for role, secret_id in {
            "api": args.api_secret,
            "migration": args.migration_secret,
        }.items()
    }
    secret_arns = [str(check["secret_arn"]) for check in runtime_secrets.values()]
    _require(len(secret_arns) == len(set(secret_arns)), "Runtime secrets are not role-separated.")
    qualification_secret = secrets_client.describe_secret(SecretId=args.qualification_secret)
    _require(
        qualification_secret.get("DeletedDate") is None,
        "The qualification secret is scheduled for deletion.",
    )
    qualification_secret_arn = str(qualification_secret["ARN"])
    _require(
        qualification_secret_arn not in secret_arns,
        "The qualification record must use a dedicated secret.",
    )
    qualification_secret_boundary = _verify_qualification_secret_boundary(
        secrets_client,
        secret_arn=qualification_secret_arn,
        qualifier_role_arn=args.qualifier_role_arn,
        expected_policy_sha256=args.qualification_secret_policy_sha256,
    )
    qualification_control_plane = _verify_qualification_control_plane(
        session.client("iam"),
        expected=qualification_control_boundary,
        qualifier_role_arn=args.qualifier_role_arn,
        deployment_role_arn=args.deployment_role_arn,
        evidence_issuer_role_arn=args.evidence_issuer_role_arn,
        signing_key_arn=args.evidence_signing_key_arn,
        qualification_secret_arn=qualification_secret_arn,
    )
    s3_check = _verify_s3(
        session.client("s3"),
        args.bucket,
        expected_kms_key_arn=args.evidence_kms_key_arn,
        expected_bucket_policy_sha256=args.evidence_bucket_policy_sha256,
    )
    rds_check = _verify_rds(
        session.client("rds"),
        args.db_instance,
        maximum_rpo_minutes=args.max_rpo_minutes,
        expected=rds_boundary,
    )
    worker_database_user = str(release["worker_database_user"])
    worker_database_url = (
        f"postgresql+psycopg://{worker_database_user}@"
        f"{rds_check['endpoint_address']}:{rds_check['endpoint_port']}/"
        f"{rds_check['database_name']}?sslmode=verify-full&sslrootcert={RDS_CA_BUNDLE_PATH}"
    )
    ecs_check = _verify_ecs(
        session.client("ecs"),
        cluster=args.cluster,
        services=[args.web_service, args.api_service, args.worker_service],
        expected_migration_task_definition_arn=args.migration_task_definition_arn,
        expected_images=cast(dict[str, str], release["images"]),
        expected_release_revision=args.git_commit,
        expected_deployment_id=args.deployment_id,
        expected_qualification_mode=args.qualification_mode,
        expected_bedrock_model_id=args.bedrock_model_id,
        expected_bedrock_classifications=cast(
            list[str], release["bedrock_allowed_data_classifications"]
        ),
        expected_secret_arns={
            role: str(check["secret_arn"]) for role, check in runtime_secrets.items()
        },
        expected_secret_version_ids={
            role: str(rotation_results[f"{role}_current_version_id"])
            for role in ("api", "migration")
        },
        expected_task_role_arns=task_role_arns,
        expected_execution_role_arns=execution_role_arns,
        expected_worker_operator_id=args.worker_operator_id,
        expected_worker_engagement_id=args.worker_engagement_id,
        expected_worker_database_url=worker_database_url,
        expected_qualifier_role_arn=args.qualifier_role_arn,
        expected_sanitized_data_enabled=False,
        expected_application_origin=str(release["application_origin"]),
        expected_oidc_issuer_url=str(release["oidc_issuer_url"]),
        expected_oidc_client_id=str(release["oidc_client_id"]),
        expected_oidc_allowed_emails=cast(list[str], release["oidc_allowed_emails"]),
        expected_s3_bucket=args.bucket,
        expected_s3_kms_key_arn=str(s3_check["kms_key_arn"]),
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
    runtime_secrets = _bind_runtime_secrets_to_ecs(runtime_secrets, ecs_check)
    worker_network = _verify_worker_network(
        session.client("ec2"),
        ecs_check=ecs_check,
        expected=worker_network_boundary,
        region=args.region,
    )
    partition = str(identity["Arn"]).split(":", maxsplit=2)[1]
    task_role_arns = cast(dict[str, str], ecs_check["task_role_arns"])
    ecs_data_role_inventory = _verify_ecs_data_role_inventory(
        session.client("iam"),
        expected=ecs_role_boundary,
        task_role_arns=task_role_arns,
        execution_role_arns=cast(
            dict[str, str], ecs_check["execution_role_arns"]
        ),
    )
    worker_s3_isolation = _verify_worker_s3_isolation(
        session.client("iam"),
        role_arn=task_role_arns["worker"],
        bucket_arn=f"arn:{partition}:s3:::{args.bucket}",
        kms_key_arn=str(s3_check["kms_key_arn"]),
        region=args.region,
        worker_engagement_id=args.worker_engagement_id,
    )
    worker_bedrock_isolation = _verify_worker_bedrock_isolation(
        session.client("iam"),
        role_arn=task_role_arns["worker"],
        model_arn=args.bedrock_model_arn,
    )
    db_user_arn = (
        f"arn:{partition}:rds-db:{args.region}:{identity['Account']}:dbuser:"
        f"{rds_check['db_resource_id']}/{worker_database_user}"
    )
    worker_database_identity = _verify_worker_database_identity(
        session.client("iam"),
        task_role_arns=task_role_arns,
        expected_worker_role_arn=args.worker_task_role_arn,
        db_user_arn=db_user_arn,
    )
    prior_worker_identity_denials = _verify_prior_worker_identity_denials(
        session.client("iam"),
        prior_role_arns=args.prior_worker_task_role_arn or [],
        current_worker_role_arn=args.worker_task_role_arn,
        db_user_arn=db_user_arn,
        bucket_arn=f"arn:{partition}:s3:::{args.bucket}",
        kms_key_arn=str(s3_check["kms_key_arn"]),
        region=args.region,
        worker_engagement_id=args.worker_engagement_id,
        bedrock_model_arn=args.bedrock_model_arn,
        revocation_evidence=cast(
            dict[str, object], external_evidence["prior_worker_revocation"]
        ),
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
    )
    checks: dict[str, Any] = {
        "https": _verify_https(
            f"{args.application_url.rstrip('/')}/api/ready",
            expected_release_revision=args.git_commit,
            expected_deployment_id=args.deployment_id,
            expected_qualification_mode=args.qualification_mode,
            expected_sanitized_data_enabled=False,
        ),
        "s3": s3_check,
        "rds": rds_check,
        "ecs": ecs_check,
        "worker_network": worker_network,
        "worker_s3_isolation": worker_s3_isolation,
        "worker_bedrock_isolation": worker_bedrock_isolation,
        "worker_database_identity": worker_database_identity,
        "bedrock_logging": _verify_bedrock_logging(session.client("bedrock")),
        "bedrock_evaluation": _verify_bedrock_evaluation(
            session.client("bedrock"),
            args.bedrock_evaluation_job,
            args.bedrock_model_id,
        ),
        "runtime_secrets": runtime_secrets,
        "qualification_secret_boundary": qualification_secret_boundary,
        "qualification_control_plane": qualification_control_plane,
        "ecs_data_role_inventory": ecs_data_role_inventory,
        "prior_worker_identity_denials": prior_worker_identity_denials,
        "standalone_task_drain": standalone_task_drain,
    }
    validated_at = datetime.now(UTC)
    record = {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "validated_at": validated_at.isoformat(),
        "expires_at": (
            validated_at + timedelta(hours=args.qualification_validity_hours)
        ).isoformat(),
        "aws_account_id": identity["Account"],
        "aws_principal_arn": identity["Arn"],
        "region": args.region,
        "status": "passed",
        "release": release,
        "external_evidence": external_evidence,
        "checks": checks,
    }
    record["validation_id"] = readiness_validation_digest(record)
    record["content_digest"] = qualification_content_digest(record)
    version_id = str(record["validation_id"]).removeprefix("sha256:")
    validate_deployment_qualification_record(
        json.dumps(record, sort_keys=True, separators=(",", ":")),
        expected_version_id=version_id,
        expected_release_revision=args.git_commit,
        expected_deployment_id=args.deployment_id,
        expected_qualification_mode=args.qualification_mode,
        expected_worker_operator_id=uuid.UUID(args.worker_operator_id),
        expected_worker_engagement_id=uuid.UUID(args.worker_engagement_id),
        expected_application_origin=str(release["application_origin"]),
        expected_oidc_issuer_url=str(release["oidc_issuer_url"]),
        expected_oidc_client_id=str(release["oidc_client_id"]),
        expected_oidc_allowed_emails=cast(list[str], release["oidc_allowed_emails"]),
        expected_region=args.region,
        expected_qualifier_role_arn=args.qualifier_role_arn,
        expected_bedrock_model_id=args.bedrock_model_id,
        expected_bedrock_classifications=cast(
            list[str], release["bedrock_allowed_data_classifications"]
        ),
        expected_s3_kms_key_arn=str(s3_check["kms_key_arn"]),
        expected_qualification_secret_policy_sha256=(
            args.qualification_secret_policy_sha256
        ),
        expected_evidence_signing_public_key_der_b64=str(
            release["evidence_signing_public_key_der_b64"]
        ),
        expected_evidence_signing_public_key_b64_sha256=str(
            release["evidence_signing_public_key_b64_sha256"]
        ),
        now=validated_at,
    )
    published_version_id = _publish_qualification_record(
        secrets_client,
        secret_id=qualification_secret_arn,
        record=record,
    )
    _require(
        published_version_id == version_id,
        "The published qualification version does not match its immutable claims.",
    )
    output = json.dumps(record, indent=2, sort_keys=True)
    if args.output:
        try:
            with args.output.open("x", encoding="utf-8") as output_file:
                output_file.write(f"{output}\n")
        except FileExistsError as error:
            raise ReadinessFailure(
                "The readiness output already exists; refusing to overwrite qualification evidence."
            ) from error
    print(output)


if __name__ == "__main__":
    main()
