output "application_url" {
  value = "https://${var.domain_name}"
}

output "runtime_secret_arns" {
  value       = { for name, secret in aws_secretsmanager_secret.runtime : name => secret.arn }
  description = "Populate only the per-role JSON keys listed in README.md before starting tasks."
}

output "runtime_secret_version_bindings" {
  value = {
    api       = var.api_runtime_secret_version_id
    migration = var.migration_runtime_secret_version_id
  }
  description = "Exact signed runtime-secret versions pinned into ECS JSON-key selectors; these must match rotation evidence and AWSCURRENT."
}

output "ecs_role_boundary" {
  value = {
    task_role_arns      = { for name in local.runtime_names : name => aws_iam_role.task[name].arn }
    execution_role_arns = { for name in local.runtime_names : name => aws_iam_role.execution[name].arn }
    data_role_contracts = {
      api_task = {
        role_arn            = aws_iam_role.task["api"].arn
        trust_policy_sha256 = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.ecs_assume.json)))}"
        inline_policy_sha256 = {
          evidence-objects = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.api_evidence_access.json)))}"
        }
        attached_managed_policy_arns = []
      }
      api_execution = {
        role_arn            = aws_iam_role.execution["api"].arn
        trust_policy_sha256 = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.ecs_assume.json)))}"
        inline_policy_sha256 = {
          runtime-secret = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.execution_secrets["api"].json)))}"
        }
        attached_managed_policy_arns = ["arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"]
      }
      migration_task = {
        role_arn            = aws_iam_role.task["migration"].arn
        trust_policy_sha256 = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.ecs_assume.json)))}"
        inline_policy_sha256 = length(local.package_retrieval_target_secret_arns) == 0 ? {} : {
          package-retrieval-secret-delivery = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.migration_retrieval_secret_delivery[0].json)))}"
        }
        attached_managed_policy_arns = []
      }
      migration_execution = {
        role_arn            = aws_iam_role.execution["migration"].arn
        trust_policy_sha256 = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.ecs_assume.json)))}"
        inline_policy_sha256 = {
          runtime-secret = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.execution_secrets["migration"].json)))}"
        }
        attached_managed_policy_arns = ["arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"]
      }
    }
  }
  description = "Exact ECS task/execution role identities and live-verifiable API/migration trust and policy digests."
}

output "qualification_secret_arn" {
  value       = aws_secretsmanager_secret.qualification.arn
  description = "Dedicated immutable qualification-record secret; only the qualifier role can publish versions."
}

output "qualification_secret_policy_sha256" {
  value       = "sha256:${sha256(jsonencode(local.qualification_secret_policy_contract))}"
  description = "Canonical digest of the exact qualification-secret resource policy verified before publication and activation."
}

output "qualification_control_boundary" {
  value = {
    qualification_secret_arn = aws_secretsmanager_secret.qualification.arn
    signing_key_arn          = aws_kms_key.evidence_signing.arn
    roles = {
      qualifier = {
        role_arn              = aws_iam_role.qualifier.arn
        trusted_principal_arn = var.qualification_principal_arn
        trust_policy_sha256   = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.qualifier_assume.json)))}"
        inline_policy_sha256 = {
          deployment-qualification = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.qualifier.json)))}"
        }
      }
      evidence_issuer = {
        role_arn              = aws_iam_role.evidence_issuer.arn
        trusted_principal_arn = var.evidence_principal_arn
        trust_policy_sha256   = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.evidence_issuer_assume.json)))}"
        inline_policy_sha256 = {
          sign-qualification-evidence = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.evidence_issuer.json)))}"
        }
      }
      deployment = {
        role_arn              = aws_iam_role.deployment.arn
        trusted_principal_arn = var.deployment_principal_arn
        trust_policy_sha256   = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.deployment_assume.json)))}"
        inline_policy_sha256 = {
          release = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.deployment.json)))}"
        }
      }
    }
  }
  description = "Exact trust and inline-policy digests for the independent qualifier, evidence issuer, and deployment roles."
}

output "qualification_version_state" {
  value = {
    pending = var.pending_qualification_record_version_id
    active  = var.active_qualification_record_version_id
  }
  description = "Pending migration binding and active runtime qualification versions; final activation requires equality."
}

output "qualifier_role_arn" {
  value       = aws_iam_role.qualifier.arn
  description = "Assume this role for candidate qualification and post-activation verification."
}

output "evidence_issuer_role_arn" {
  value       = aws_iam_role.evidence_issuer.arn
  description = "Independent role authorized to KMS-sign typed external qualification evidence."
}

output "evidence_signing_key_arn" {
  value       = aws_kms_key.evidence_signing.arn
  description = "Asymmetric AWS KMS key used to authenticate external qualification evidence."
}

output "evidence_signing_public_key" {
  value = {
    der_b64         = data.aws_kms_public_key.evidence_signing.public_key
    b64_sha256      = "sha256:${sha256(data.aws_kms_public_key.evidence_signing.public_key)}"
    signing_key_arn = aws_kms_key.evidence_signing.arn
  }
  description = "Release-pinned offline trust anchor for runtime evidence verification."
}

output "migration_runner_role_arn" {
  value       = aws_iam_role.migration_runner.arn
  description = "Operations caller role authorized only to start the fixed migration state machine."
}

output "migration_state_machine_arn" {
  value       = aws_sfn_state_machine.migration.arn
  description = "Start this broker to run the exact migration revision with Terraform-owned network and role parameters."
}

output "migration_task_definition_arn" {
  value       = aws_ecs_task_definition.migration.arn
  description = "Exact migration task revision pinned into the fixed broker and activation proof."
}

output "worker_task_role_arn" {
  value       = aws_iam_role.task["worker"].arn
  description = "Release-scoped worker workload identity authorized for RDS IAM authentication."
}

output "worker_database_user" {
  value       = local.worker_database_user
  description = "Release-scoped RDS IAM login derived from deployment_id and release_revision."
}

output "rds_master_secret_arn" {
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
  description = "Bootstrap-only owner credential; applications use scoped roles in runtime secret."
  sensitive   = true
}

output "evidence_bucket" {
  value = aws_s3_bucket.evidence.id
}

output "evidence_kms_key_arn" {
  value       = aws_kms_key.evidence.arn
  description = "Dedicated rotating customer-managed key required for every evidence object write."
}

output "evidence_bucket_policy_sha256" {
  value       = "sha256:${sha256(jsonencode(jsondecode(data.aws_iam_policy_document.evidence_bucket.json)))}"
  description = "Canonical digest of the evidence bucket transport and encryption boundary."
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "private_subnets" {
  value = aws_subnet.private[*].id
}

output "task_security_groups" {
  value = {
    web       = aws_security_group.web_tasks.id
    api       = aws_security_group.api_tasks.id
    worker    = aws_security_group.worker_tasks.id
    migration = aws_security_group.migration_tasks.id
  }
  description = "Read-only security-group inventory; task launch configuration remains Terraform-owned."
}

output "worker_network_boundary" {
  value = {
    vpc_id                     = aws_vpc.main.id
    vpc_cidr                   = aws_vpc.main.cidr_block
    worker_security_group_id   = aws_security_group.worker_tasks.id
    worker_subnet_ids          = sort(aws_subnet.worker_private[*].id)
    worker_route_table_id      = aws_route_table.worker_private.id
    database_security_group_id = aws_security_group.database.id
    endpoint_security_group_id = aws_security_group.private_endpoints.id
    endpoint_ingress_security_group_ids = sort([
      aws_security_group.web_tasks.id,
      aws_security_group.api_tasks.id,
      aws_security_group.worker_tasks.id,
      aws_security_group.migration_tasks.id,
    ])
    s3_prefix_list_id = aws_vpc_endpoint.s3.prefix_list_id
    vpc_resolver_cidr = "${cidrhost(var.vpc_cidr, 2)}/32"
    vpc_endpoints = merge(
      {
        s3 = {
          id              = aws_vpc_endpoint.s3.id
          service_name    = aws_vpc_endpoint.s3.service_name
          type            = aws_vpc_endpoint.s3.vpc_endpoint_type
          policy_sha256   = "sha256:${sha256(local.s3_endpoint_policy)}"
          route_table_ids = sort(aws_vpc_endpoint.s3.route_table_ids)
        }
      },
      {
        for name, endpoint in aws_vpc_endpoint.interface : name => {
          id                 = endpoint.id
          service_name       = endpoint.service_name
          type               = endpoint.vpc_endpoint_type
          policy_sha256      = "sha256:${sha256(local.interface_endpoint_policies[name])}"
          subnet_ids         = sort(endpoint.subnet_ids)
          security_group_ids = sort(endpoint.security_group_ids)
        }
      },
    )
  }
  description = "Exact no-NAT worker subnet, egress, route, and private endpoint qualification contract."
}

output "rds_boundary" {
  value = {
    identifier          = aws_db_instance.postgres.identifier
    engine              = aws_db_instance.postgres.engine
    vpc_id              = aws_vpc.main.id
    database_subnet_ids = sort(aws_subnet.private[*].id)
    security_group_ids  = sort(aws_db_instance.postgres.vpc_security_group_ids)
    kms_key_arn         = aws_kms_key.data.arn
    endpoint_address    = aws_db_instance.postgres.address
    endpoint_port       = aws_db_instance.postgres.port
    database_name       = aws_db_instance.postgres.db_name
    ca_bundle_path      = local.rds_ca_bundle_path
    ca_bundle_sha256    = local.rds_ca_bundle_sha256
  }
  description = "Exact Terraform-owned private RDS configuration and pinned client trust bundle qualification contract."
}

output "deployment_role_arn" {
  value = aws_iam_role.deployment.arn
}

output "ecr_repositories" {
  value = { for name, repository in aws_ecr_repository.runtime : name => repository.repository_url }
}

output "operations_dashboard" {
  value       = aws_cloudwatch_dashboard.operations.dashboard_name
  description = "CloudWatch dashboard for the controlled design-partner runtime."
}

output "mission_control_integration_log_group" {
  value = {
    name = aws_cloudwatch_log_group.mission_control_integration.name
    arn  = aws_cloudwatch_log_group.mission_control_integration.arn
  }
  description = "Destination contract for separately authorized metadata-only Mission Control importer events."
}

output "alarm_names" {
  value       = concat(values(aws_cloudwatch_metric_alarm.target_unhealthy)[*].alarm_name, values(aws_cloudwatch_metric_alarm.runtime)[*].alarm_name)
  description = "Actionable alarms; notification actions are attached only when alarm_topic_arn is set."
}
