from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TERRAFORM = ROOT / "infrastructure" / "terraform" / "design-partner"
RDS_CA_SHA256 = "e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
RDS_CA_PATH = "/opt/ai-fde/certs/aws-rds-global-bundle.pem"
RDS_CA_URL = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _hcl_block(source: str, kind: str, block_type: str, name: str) -> str:
    match = re.search(
        rf'{re.escape(kind)}\s+"{re.escape(block_type)}"\s+"{re.escape(name)}"\s*\{{',
        source,
    )
    assert match is not None, f"Missing {kind} {block_type}.{name}"
    start = match.start()
    depth = 0
    for index in range(match.end() - 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Unterminated {kind} {block_type}.{name}")


def _workflow_step(source: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    start = source.find(marker)
    assert start >= 0, f"Missing workflow step {name}"
    end = source.find("\n      - name:", start + len(marker))
    return source[start:] if end < 0 else source[start:end]


def test_ci_validates_terraform_offline_with_immutable_tooling() -> None:
    workflow = _read(ROOT / ".github" / "workflows" / "ci.yml")
    setup = _workflow_step(workflow, "Install Terraform")
    validation = _workflow_step(workflow, "Validate design-partner Terraform")
    containers = _workflow_step(
        workflow,
        "Build containers and verify the non-root RDS trust bundle",
    )

    assert (
        "uses: hashicorp/setup-terraform@dfe3c3f87815947d99a8997f908cb6525fc44e9e"
        in setup
    )
    assert "# v4.0.1" in setup
    assert 'terraform_version: "1.16.1"' in setup
    assert "terraform_wrapper: false" in setup
    assert "working-directory: infrastructure/terraform/design-partner" in validation
    assert 'AWS_EC2_METADATA_DISABLED: "true"' in validation
    assert 'TF_IN_AUTOMATION: "true"' in validation
    assert "terraform fmt -check -recursive" in validation
    assert "terraform init -backend=false -input=false" in validation
    assert "terraform validate" in validation
    assert validation.count("terraform ") == 3
    for forbidden in (
        "terraform apply",
        "terraform plan",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "role-to-assume",
    ):
        assert forbidden not in validation

    assert "docker build --file docker/api.Dockerfile --tag ai-fde-api:ci ." in containers
    assert "docker build --file docker/worker.Dockerfile --tag ai-fde-worker:ci ." in containers
    assert "docker run --rm --entrypoint sha256sum" in containers


def test_worker_has_no_public_https_egress_and_uses_only_private_service_boundaries() -> None:
    network = _read(TERRAFORM / "network.tf")
    ecs = _read(TERRAFORM / "ecs.tf")
    worker = _hcl_block(network, "resource", "aws_security_group", "worker_tasks")
    worker_subnet = _hcl_block(network, "resource", "aws_subnet", "worker_private")
    worker_routes = _hcl_block(
        network,
        "resource",
        "aws_route_table",
        "worker_private",
    )
    worker_service = _hcl_block(ecs, "resource", "aws_ecs_service", "worker")
    worker_database = _hcl_block(
        network, "resource", "aws_vpc_security_group_egress_rule", "worker_database"
    )
    worker_endpoints = _hcl_block(
        network,
        "resource",
        "aws_vpc_security_group_egress_rule",
        "worker_private_endpoints",
    )
    worker_s3 = _hcl_block(network, "resource", "aws_vpc_security_group_egress_rule", "worker_s3")

    assert "egress = []" in worker
    assert "0.0.0.0/0" not in worker
    assert "referenced_security_group_id = aws_security_group.database.id" in worker_database
    assert (
        "referenced_security_group_id = aws_security_group.private_endpoints.id" in worker_endpoints
    )
    assert "prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id" in worker_s3
    assert 'cidr_blocks = ["0.0.0.0/0"]' not in worker_database + worker_endpoints + worker_s3
    assert "map_public_ip_on_launch = false" in worker_subnet
    assert "route {" not in worker_routes
    assert "aws_nat_gateway" not in worker_routes
    assert "aws_internet_gateway" not in worker_routes
    assert "subnets          = aws_subnet.worker_private[*].id" in worker_service
    assert "assign_public_ip = false" in worker_service


def test_private_endpoints_have_private_dns_and_bounded_service_policies() -> None:
    network = _read(TERRAFORM / "network.tf")
    endpoints = _hcl_block(network, "resource", "aws_vpc_endpoint", "interface")
    s3 = _hcl_block(network, "resource", "aws_vpc_endpoint", "s3")

    assert "private_dns_enabled = true" in endpoints
    assert "security_group_ids  = [aws_security_group.private_endpoints.id]" in endpoints
    for service in (
        "secretsmanager",
        "bedrock-runtime",
        '"ecr.api"',
        '"ecr.dkr"',
        "logs",
    ):
        assert service in network
    assert "policy            = local.s3_endpoint_policy" in s3
    assert "aws_s3_bucket.evidence.arn" in network
    assert "prod-${var.aws_region}-starport-layer-bucket/*" in network
    assert "var.bedrock_model_arn" in network
    assert "values(aws_ecr_repository.runtime)[*].arn" in network
    assert "values(aws_secretsmanager_secret.runtime)[*].arn" in network
    assert "aws_cloudwatch_log_group.runtime" in network
    # The only unavoidable wildcard resource is ECR GetAuthorizationToken; runtime IAM still
    # controls the caller and every data-plane endpoint policy uses exact resources.
    assert network.count('Resource  = "*"') == 1
    assert 'Action    = ["ecr:GetAuthorizationToken"]' in network


def test_human_roles_cannot_choose_migration_task_network_or_roles() -> None:
    iam = _read(TERRAFORM / "iam.tf")
    deployment = _hcl_block(iam, "data", "aws_iam_policy_document", "deployment")
    migration_caller = _hcl_block(iam, "data", "aws_iam_policy_document", "migration_runner")

    assert "ecs:RegisterTaskDefinition" not in deployment
    assert "ecs:RunTask" not in deployment
    assert "ecs:UpdateService" not in deployment
    assert "iam:PassRole" not in deployment
    assert 'aws_iam_role.execution["migration"].arn' not in deployment
    assert 'aws_iam_role.task["migration"].arn' not in deployment
    assert 'actions   = ["states:StartExecution"]' in migration_caller
    assert "resources = [aws_sfn_state_machine.migration.arn]" in migration_caller
    assert migration_caller.count("statement {") == 1
    for forbidden in (
        "ecs:RunTask",
        "ecs:DescribeTasks",
        "ecs:StopTask",
        "iam:PassRole",
        "aws_ecs_task_definition",
        "aws_subnet",
        "aws_security_group",
        "aws_iam_role.execution",
        "aws_iam_role.task",
    ):
        assert forbidden not in migration_caller


def test_task_roles_require_a_deliberate_quarantine_handoff_before_rotation() -> None:
    iam = _read(TERRAFORM / "iam.tf")
    task_roles = _hcl_block(iam, "resource", "aws_iam_role", "task")

    assert "lifecycle {" in task_roles
    assert "prevent_destroy = true" in task_roles
    assert "prevent_destroy = false" not in task_roles

    variables = _read(TERRAFORM / "variables.tf")
    prior_roles = variables.split(
        'variable "prior_worker_task_role_arns"',
        maxsplit=1,
    )[1].split('\nvariable "', maxsplit=1)[0]
    assert "default" not in prior_roles

    example = _read(TERRAFORM / "terraform.tfvars.example")
    assert "prior_worker_task_role_arns = []" in example


def test_step_functions_broker_hardcodes_the_exact_migration_boundary() -> None:
    broker = _read(TERRAFORM / "migration_broker.tf")
    assume = _hcl_block(broker, "data", "aws_iam_policy_document", "migration_broker_assume")
    execution = _hcl_block(broker, "data", "aws_iam_policy_document", "migration_broker")
    state_machine = _hcl_block(broker, "resource", "aws_sfn_state_machine", "migration")

    assert 'identifiers = ["states.amazonaws.com"]' in assume
    assert 'variable = "aws:SourceAccount"' in assume
    assert 'variable = "aws:SourceArn"' in assume
    assert "values   = [local.migration_state_machine_arn]" in assume

    assert 'actions   = ["ecs:RunTask"]' in execution
    assert "ecs:RegisterTaskDefinition" not in execution
    assert "resources = [aws_ecs_task_definition.migration.arn]" in execution
    assert 'variable = "ecs:cluster"' in execution
    assert 'variable = "ecs:task-definition"' in execution
    assert 'variable = "ecs:subnet"' in execution
    assert 'variable = "ecs:auto-assign-public-ip"' in execution
    assert 'variable = "ecs:enable-execute-command"' in execution
    assert execution.count('test     = "Bool"') == 2
    public_ip_condition = re.search(
        r'variable = "ecs:auto-assign-public-ip"\s+values\s+= \["false"\]',
        execution,
    )
    execute_command_condition = re.search(
        r'variable = "ecs:enable-execute-command"\s+values\s+= \["false"\]',
        execution,
    )
    assert public_ip_condition is not None
    assert execute_command_condition is not None
    assert 'actions   = ["iam:PassRole"]' in execution
    assert 'aws_iam_role.execution["migration"].arn' in execution
    assert 'aws_iam_role.task["migration"].arn' in execution
    for required_event_action in (
        "events:DescribeRule",
        "events:PutRule",
        "events:PutTargets",
    ):
        assert required_event_action in execution
    assert "resources = [local.step_functions_ecs_rule_arn]" in execution

    assert (
        'Resource = "arn:${data.aws_partition.current.partition}:states:::ecs:runTask.sync"'
        in state_machine
    )
    assert "role_arn = aws_iam_role.migration_broker.arn" in state_machine
    assert "aws_iam_role.migration_runner" not in state_machine
    assert "Cluster              = aws_ecs_cluster.main.arn" in state_machine
    assert "TaskDefinition       = aws_ecs_task_definition.migration.arn" in state_machine
    assert 'LaunchType           = "FARGATE"' in state_machine
    assert "EnableExecuteCommand = false" in state_machine
    assert "Subnets        = sort(aws_subnet.private[*].id)" in state_machine
    assert "SecurityGroups = [aws_security_group.migration_tasks.id]" in state_machine
    assert 'AssignPublicIp = "DISABLED"' in state_machine
    assert re.search(r"TimeoutSeconds\s*=\s*1800", state_machine)
    assert 'Variable      = "$.migration_task.Containers[0].ExitCode"' in state_machine
    assert "NumericEquals = 0" in state_machine
    assert "Overrides" not in state_machine
    for caller_selected_path in (
        "Cluster.$",
        "TaskDefinition.$",
        "Subnets.$",
        "SecurityGroups.$",
        "AssignPublicIp.$",
        "EnableExecuteCommand.$",
    ):
        assert caller_selected_path not in state_machine


def test_evidence_uses_separate_asymmetric_kms_signer_and_trusted_issuer() -> None:
    data = _read(TERRAFORM / "data.tf")
    iam = _read(TERRAFORM / "iam.tf")
    variables = _read(TERRAFORM / "variables.tf")
    signing_key = _hcl_block(data, "resource", "aws_kms_key", "evidence_signing")
    issuer = _hcl_block(iam, "data", "aws_iam_policy_document", "evidence_issuer")
    qualifier = _hcl_block(iam, "data", "aws_iam_policy_document", "qualifier")

    assert 'key_usage                = "SIGN_VERIFY"' in signing_key
    assert 'customer_master_key_spec = "RSA_3072"' in signing_key
    assert 'actions   = ["kms:GetPublicKey", "kms:Sign"]' in issuer
    assert 'actions   = ["kms:GetPublicKey", "kms:Verify"]' in qualifier
    assert "kms:Sign" not in qualifier
    assert 'variable "evidence_principal_arn"' in variables
    assert 'variable "prior_worker_task_role_arns"' in variables
    assert "length(var.prior_worker_task_role_arns) > 0" not in variables
    assert "explicitly empty or sorted unique" in variables


def test_worker_identity_rotates_for_every_release_even_with_a_reused_label() -> None:
    iam = _read(TERRAFORM / "iam.tf")

    assert (
        'substr(sha256("${var.deployment_id}:${var.release_revision}"), 0, 12)'
        in iam
    )
    assert 'worker_database_user   = "ai_fde_worker_${local.worker_identity_suffix}"' in iam


def test_ecs_role_boundary_exports_exact_live_verifiable_role_contracts() -> None:
    iam = _read(TERRAFORM / "iam.tf")
    outputs = _read(TERRAFORM / "outputs.tf")
    qualifier = _hcl_block(iam, "data", "aws_iam_policy_document", "qualifier")

    assert 'output "ecs_role_boundary"' in outputs
    assert "values(aws_iam_role.task)[*].arn" in qualifier
    assert "values(aws_iam_role.execution)[*].arn" in qualifier
    assert "task_role_arns" in outputs
    assert "execution_role_arns" in outputs
    for role_kind in (
        "api_task",
        "api_execution",
        "migration_task",
        "migration_execution",
    ):
        assert role_kind in outputs
    assert outputs.count("trust_policy_sha256") >= 4
    assert outputs.count("inline_policy_sha256") >= 4
    assert outputs.count("attached_managed_policy_arns") >= 4
    assert "jsonencode(jsondecode(data.aws_iam_policy_document.ecs_assume.json))" in outputs
    assert "data.aws_iam_policy_document.api_evidence_access.json" in outputs
    assert 'data.aws_iam_policy_document.execution_secrets["api"].json' in outputs
    assert 'data.aws_iam_policy_document.execution_secrets["migration"].json' in outputs


def test_evidence_storage_requires_a_dedicated_key_tls_and_exact_sse_headers() -> None:
    data = _read(TERRAFORM / "data.tf")
    ecs = _read(TERRAFORM / "ecs.tf")
    outputs = _read(TERRAFORM / "outputs.tf")
    evidence_key = _hcl_block(data, "resource", "aws_kms_key", "evidence")
    default_encryption = _hcl_block(
        data,
        "resource",
        "aws_s3_bucket_server_side_encryption_configuration",
        "evidence",
    )
    bucket_boundary = _hcl_block(data, "data", "aws_iam_policy_document", "evidence_bucket")
    bucket_policy = _hcl_block(data, "resource", "aws_s3_bucket_policy", "evidence")

    assert "enable_key_rotation     = true" in evidence_key
    assert "aws_kms_key.data" not in evidence_key
    assert "kms_master_key_id = aws_kms_key.evidence.arn" in default_encryption
    assert "bucket_key_enabled = true" in default_encryption
    assert 'sid     = "DenyInsecureTransport"' in bucket_boundary
    assert 'variable = "aws:SecureTransport"' in bucket_boundary
    assert 'sid       = "DenyMissingSSEKMS"' in bucket_boundary
    assert 'test     = "Null"' in bucket_boundary
    assert 'sid       = "DenyWrongSSEAlgorithm"' in bucket_boundary
    assert 'variable = "s3:x-amz-server-side-encryption"' in bucket_boundary
    assert 'values   = ["aws:kms"]' in bucket_boundary
    assert 'sid       = "DenyWrongKMSKey"' in bucket_boundary
    assert 'variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"' in bucket_boundary
    assert "values   = [aws_kms_key.evidence.arn]" in bucket_boundary
    assert len(re.findall(r'effect\s*=\s*"Deny"', bucket_boundary)) == 4
    assert bucket_boundary.count('actions   = ["s3:PutObject"]') == 3
    assert "policy = data.aws_iam_policy_document.evidence_bucket.json" in bucket_policy
    assert 'name = "AI_FDE_S3_KMS_KEY_ARN"' in ecs
    assert "value = aws_kms_key.evidence.arn" in ecs
    assert 'output "evidence_kms_key_arn"' in outputs
    assert (
        "sha256(jsonencode(jsondecode(data.aws_iam_policy_document.evidence_bucket.json)))"
        in outputs
    )


def test_evidence_roles_and_gateway_endpoint_cannot_escape_the_bucket_boundary() -> None:
    iam = _read(TERRAFORM / "iam.tf")
    network = _read(TERRAFORM / "network.tf")
    ecs = _read(TERRAFORM / "ecs.tf")
    api = _hcl_block(iam, "data", "aws_iam_policy_document", "api_evidence_access")
    worker = _hcl_block(iam, "data", "aws_iam_policy_document", "worker_evidence_read")
    qualifier = _hcl_block(iam, "data", "aws_iam_policy_document", "qualifier")

    for policy in (api, worker):
        assert "aws_kms_key.evidence.arn" in policy
        assert "aws_kms_key.data.arn" not in policy
        assert 'variable = "kms:ViaService"' in policy
        assert 'values   = ["s3.${var.aws_region}.amazonaws.com"]' in policy
        assert 'variable = "kms:EncryptionContext:aws:s3:arn"' in policy
        assert "values   = [aws_s3_bucket.evidence.arn]" in policy
    assert 'actions   = ["s3:GetBucketLocation"]' in api
    assert 'actions   = ["s3:ListBucket", "s3:ListBucketVersions"]' in api
    assert '      "s3:GetObject",' in api
    assert '      "s3:GetObjectVersion",' in api
    assert '      "kms:Encrypt",' not in api
    assert "s3:PutObject" not in worker
    assert "s3:DeleteObject" not in worker
    assert "s3:ListBucket" not in worker
    assert "s3:GetBucketPolicy" in qualifier

    assert 'Sid       = "APIEvidenceBucket"' in network
    assert 'Sid       = "APIEvidenceObjects"' in network
    assert 'Sid       = "WorkerEvidenceObjects"' in network
    assert network.count('"aws:PrincipalArn" = aws_iam_role.task["api"].arn') == 3
    assert network.count('"aws:PrincipalArn" = aws_iam_role.task["worker"].arn') == 1
    assert (
        'Resource  = "${aws_s3_bucket.evidence.arn}/engagements/'
        '${coalesce(var.worker_engagement_id, "disabled")}/evidence/*"'
    ) in network
    assert 'Sid       = "EvidenceObjects"' not in network
    assert 'name = "AI_FDE_S3_KMS_KEY_ARN"' in ecs


def test_api_and_worker_images_pin_the_official_rds_ca_bundle() -> None:
    for dockerfile_name in ("api.Dockerfile", "worker.Dockerfile"):
        dockerfile = _read(ROOT / "docker" / dockerfile_name)
        directory_install = "install -d --mode=0555 /opt/ai-fde/certs"
        bundle_copy = "COPY --from=rds-ca --chmod=0444"
        assert RDS_CA_URL in dockerfile
        assert RDS_CA_SHA256 in dockerfile
        assert "sha256sum --check --strict" in dockerfile
        assert RDS_CA_PATH in dockerfile
        assert directory_install in dockerfile
        assert bundle_copy in dockerfile
        assert dockerfile.index(directory_install) < dockerfile.index(bundle_copy)
        assert dockerfile.index(bundle_copy) < dockerfile.index("USER ai-fde")

    ecs = _read(TERRAFORM / "ecs.tf")
    iam = _read(TERRAFORM / "iam.tf")
    assert RDS_CA_PATH in ecs
    assert f"sha256:{RDS_CA_SHA256}" in ecs
    assert "sslmode=verify-full&sslrootcert=${local.rds_ca_bundle_path}" in ecs
    assert "${local.worker_database_user}" in ecs
    assert '/ai_fde_worker"]' not in iam
    assert '/${local.worker_database_user}"]' in iam


def test_ecs_runtime_secrets_are_pinned_to_exact_signed_versions() -> None:
    ecs = _read(TERRAFORM / "ecs.tf")
    variables = _read(TERRAFORM / "variables.tf")
    outputs = _read(TERRAFORM / "outputs.tf")

    for runtime_name in ("api", "migration"):
        variable_name = f"{runtime_name}_runtime_secret_version_id"
        assert f'variable "{variable_name}"' in variables
        assert f"var.{variable_name}" in ecs
        assert re.search(
            rf"{runtime_name}\s+=\s+var\.{variable_name}", outputs
        )
    for secret_name, variable_name in (
        ("AI_FDE_DATABASE_URL", "api_runtime_secret_version_id"),
        ("AI_FDE_OIDC_CLIENT_SECRET", "api_runtime_secret_version_id"),
        ("AI_FDE_MIGRATION_DATABASE_URL", "migration_runtime_secret_version_id"),
        ("AI_FDE_APP_DATABASE_PASSWORD", "migration_runtime_secret_version_id"),
    ):
        assert f":{secret_name}::${{var.{variable_name}}}" in ecs
        assert f":{secret_name}::\"" not in ecs

    api_task = _hcl_block(ecs, "resource", "aws_ecs_task_definition", "api")
    worker_task = _hcl_block(ecs, "resource", "aws_ecs_task_definition", "worker")
    migration_task = _hcl_block(
        ecs, "resource", "aws_ecs_task_definition", "migration"
    )
    assert "local.pending_qualification_environment" not in api_task + worker_task
    assert "local.pending_qualification_record_secret" not in api_task + worker_task
    assert "local.active_qualification_environment" in api_task + worker_task
    assert "local.pending_qualification_environment" in migration_task
    assert "local.pending_qualification_record_secret" not in migration_task
    assert "local.active_qualification_environment" not in migration_task
