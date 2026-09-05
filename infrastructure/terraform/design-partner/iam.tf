locals {
  runtime_names          = toset(["web", "api", "worker", "migration"])
  worker_identity_suffix = substr(sha256("${var.deployment_id}:${var.release_revision}"), 0, 12)
  worker_database_user   = "ai_fde_worker_${local.worker_identity_suffix}"
}

resource "aws_ecr_repository" "runtime" {
  for_each             = toset(["web", "api", "worker"])
  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration { scan_on_push = true }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.data.arn
  }
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${data.aws_partition.current.partition}:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "execution" {
  for_each           = local.runtime_names
  name               = "${local.name}-${each.key}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  for_each   = local.runtime_names
  role       = aws_iam_role.execution[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  for_each = aws_secretsmanager_secret.runtime
  statement {
    sid       = "ReadRuntimeSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [each.value.arn, aws_secretsmanager_secret.qualification.arn]
  }
  statement {
    sid       = "DecryptRuntimeSecret"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.data.arn]
  }
}

data "aws_iam_policy_document" "worker_execution_qualification" {
  statement {
    sid       = "ReadPinnedQualification"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.qualification.arn]
  }
  statement {
    sid       = "DecryptPinnedQualification"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.data.arn]
  }
}

resource "aws_iam_role_policy" "worker_execution_qualification" {
  name   = "qualification-secret"
  role   = aws_iam_role.execution["worker"].id
  policy = data.aws_iam_policy_document.worker_execution_qualification.json
}

resource "aws_iam_role_policy" "execution_secrets" {
  for_each = data.aws_iam_policy_document.execution_secrets
  name     = "runtime-secret"
  role     = aws_iam_role.execution[each.key].id
  policy   = each.value.json
}

resource "aws_iam_role" "task" {
  for_each = local.runtime_names
  name = each.key == "worker" ? (
    "${substr(local.name, 0, 35)}-worker-${local.worker_identity_suffix}-task"
  ) : "${local.name}-${each.key}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  # Release rotation must quarantine and retain the superseded worker role.
  # A normal apply therefore fails instead of silently destroying it.
  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "worker_database_connect" {
  statement {
    sid       = "ConnectAsDeploymentWorker"
    actions   = ["rds-db:connect"]
    resources = ["arn:${data.aws_partition.current.partition}:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.postgres.resource_id}/${local.worker_database_user}"]
  }
}

resource "aws_iam_role_policy" "worker_database_connect" {
  name   = "deployment-worker-database-connect"
  role   = aws_iam_role.task["worker"].id
  policy = data.aws_iam_policy_document.worker_database_connect.json
}

data "aws_iam_policy_document" "api_evidence_access" {
  statement {
    sid       = "CheckEvidenceBucketLocation"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.evidence.arn]
  }
  statement {
    sid       = "CheckEvidenceBucket"
    actions   = ["s3:ListBucket", "s3:ListBucketVersions"]
    resources = [aws_s3_bucket.evidence.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["engagements/*/evidence/*"]
    }
  }
  statement {
    sid = "ManageEvidenceObjects"
    actions = [
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.evidence.arn}/engagements/*/evidence/*"]
  }
  statement {
    sid = "UseEvidenceKey"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.evidence.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = [aws_s3_bucket.evidence.arn]
    }
  }
}

data "aws_iam_policy_document" "worker_evidence_read" {
  count = var.worker_engagement_id == null ? 0 : 1

  statement {
    sid       = "ReadEvidenceObjects"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.evidence.arn}/engagements/${coalesce(var.worker_engagement_id, "disabled")}/evidence/*"]
  }
  statement {
    sid       = "DecryptEvidenceObjects"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.evidence.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = [aws_s3_bucket.evidence.arn]
    }
  }
}

resource "aws_iam_role_policy" "api_evidence" {
  name   = "evidence-objects"
  role   = aws_iam_role.task["api"].id
  policy = data.aws_iam_policy_document.api_evidence_access.json
}

resource "aws_iam_role_policy" "worker_evidence" {
  count = var.worker_engagement_id == null ? 0 : 1

  name   = "evidence-read-only"
  role   = aws_iam_role.task["worker"].id
  policy = data.aws_iam_policy_document.worker_evidence_read[0].json
}

data "aws_iam_policy_document" "bedrock" {
  statement {
    sid       = "InvokeSelectedModel"
    actions   = ["bedrock:InvokeModel"]
    resources = [var.bedrock_model_arn]
  }
}

resource "aws_iam_role_policy" "worker_bedrock" {
  name   = "bedrock-extraction"
  role   = aws_iam_role.task["worker"].id
  policy = data.aws_iam_policy_document.bedrock.json

  lifecycle {
    precondition {
      condition = startswith(
        var.bedrock_model_arn,
        "arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}::foundation-model/",
      )
      error_message = "bedrock_model_arn must use the active AWS partition and configured region."
    }
    precondition {
      condition = var.bedrock_model_id == trimprefix(
        var.bedrock_model_arn,
        "arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}::foundation-model/",
      )
      error_message = "bedrock_model_id must be the exact foundation-model resource ID."
    }
  }
}

locals {
  package_retrieval_target_secret_arns = (
    var.package_retrieval_target_secret_arn == null ? [] : [var.package_retrieval_target_secret_arn]
  )
}

data "aws_iam_policy_document" "migration_retrieval_secret_delivery" {
  count = length(local.package_retrieval_target_secret_arns)

  statement {
    sid       = "DeliverPackageRetrievalGrant"
    actions   = ["secretsmanager:PutSecretValue"]
    resources = local.package_retrieval_target_secret_arns
  }

  dynamic "statement" {
    for_each = var.package_retrieval_target_kms_key_arn == null ? [] : [var.package_retrieval_target_kms_key_arn]

    content {
      sid       = "EncryptPackageRetrievalGrant"
      actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
      resources = [statement.value]

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["secretsmanager.${var.aws_region}.amazonaws.com"]
      }

      condition {
        test     = "StringEquals"
        variable = "kms:EncryptionContext:SecretARN"
        values   = local.package_retrieval_target_secret_arns
      }
    }
  }
}

resource "aws_iam_role_policy" "migration_retrieval_secret_delivery" {
  count = length(local.package_retrieval_target_secret_arns)

  name   = "package-retrieval-secret-delivery"
  role   = aws_iam_role.task["migration"].id
  policy = data.aws_iam_policy_document.migration_retrieval_secret_delivery[0].json
}

data "aws_iam_policy_document" "qualifier_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.qualification_principal_arn]
    }
  }
}

resource "aws_iam_role" "qualifier" {
  name               = "${local.name}-qualifier"
  assume_role_policy = data.aws_iam_policy_document.qualifier_assume.json

  lifecycle {
    precondition {
      condition = length(distinct([
        var.qualification_principal_arn,
        var.deployment_principal_arn,
        var.evidence_principal_arn,
        var.migration_principal_arn,
      ])) == 4
      error_message = "Deployment, qualification, evidence signing, and migration require four distinct principals."
    }
    precondition {
      condition     = !contains(var.prior_worker_task_role_arns, aws_iam_role.task["worker"].arn)
      error_message = "prior_worker_task_role_arns cannot include the current worker role."
    }
    precondition {
      condition = alltrue([
        for principal_arn in [
          var.deployment_principal_arn,
          var.qualification_principal_arn,
          var.evidence_principal_arn,
          var.migration_principal_arn,
          ] : startswith(
          principal_arn,
          "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:",
        )
      ])
      error_message = "All control principals must belong to the active AWS partition and deployment account."
    }
  }
}

data "aws_iam_policy_document" "evidence_issuer_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.evidence_principal_arn]
    }
  }
}

resource "aws_iam_role" "evidence_issuer" {
  name               = "${local.name}-evidence-issuer"
  assume_role_policy = data.aws_iam_policy_document.evidence_issuer_assume.json
}

data "aws_iam_policy_document" "evidence_issuer" {
  statement {
    sid       = "SignQualificationEvidence"
    actions   = ["kms:GetPublicKey", "kms:Sign"]
    resources = [aws_kms_key.evidence_signing.arn]
  }
}

resource "aws_iam_role_policy" "evidence_issuer" {
  name   = "sign-qualification-evidence"
  role   = aws_iam_role.evidence_issuer.id
  policy = data.aws_iam_policy_document.evidence_issuer.json
}

data "aws_iam_policy_document" "qualifier" {
  statement {
    sid = "ReadDeploymentConfiguration"
    actions = [
      "bedrock:GetEvaluationJob",
      "bedrock:GetModelInvocationLoggingConfiguration",
      "ec2:DescribeRouteTables",
      "ec2:DescribeSecurityGroupRules",
      "ec2:DescribeSubnets",
      "ec2:DescribeVpcEndpoints",
      "ecs:DescribeServices",
      "ecs:DescribeTasks",
      "ecs:DescribeTaskDefinition",
      "ecs:ListTasks",
      "rds:DescribeDBInstances",
      "rds:DescribeDBParameters",
    ]
    resources = ["*"]
  }
  statement {
    sid = "ReadEvidenceBucketControls"
    actions = [
      "s3:GetBucketPolicy",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketVersioning",
      "s3:GetEncryptionConfiguration",
      "s3:GetLifecycleConfiguration",
    ]
    resources = [aws_s3_bucket.evidence.arn]
  }
  statement {
    sid = "SimulateRuntimeBoundaries"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:ListRolePolicies",
      "iam:SimulatePrincipalPolicy",
    ]
    resources = concat(
      values(aws_iam_role.task)[*].arn,
      values(aws_iam_role.execution)[*].arn,
      var.prior_worker_task_role_arns,
      [
        aws_iam_role.qualifier.arn,
        aws_iam_role.evidence_issuer.arn,
        aws_iam_role.deployment.arn,
      ],
    )
  }
  statement {
    sid       = "VerifyQualificationEvidenceSignatures"
    actions   = ["kms:GetPublicKey", "kms:Verify"]
    resources = [aws_kms_key.evidence_signing.arn]
  }
  statement {
    sid = "DescribeRuntimeSecrets"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetResourcePolicy",
      "secretsmanager:ListSecretVersionIds",
    ]
    resources = concat(values(aws_secretsmanager_secret.runtime)[*].arn, [aws_secretsmanager_secret.qualification.arn])
  }
  statement {
    sid = "PublishAndReadQualificationVersions"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:PutSecretValue",
    ]
    resources = [aws_secretsmanager_secret.qualification.arn]
  }
  statement {
    sid = "UseQualificationEncryptionKey"
    actions = [
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.data.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${var.aws_region}.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:SecretARN"
      values   = [aws_secretsmanager_secret.qualification.arn]
    }
  }
}

resource "aws_iam_role_policy" "qualifier" {
  name   = "deployment-qualification"
  role   = aws_iam_role.qualifier.id
  policy = data.aws_iam_policy_document.qualifier.json
}

data "aws_iam_policy_document" "migration_runner_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.migration_principal_arn]
    }
  }
}

resource "aws_iam_role" "migration_runner" {
  name               = "${local.name}-migration-runner"
  assume_role_policy = data.aws_iam_policy_document.migration_runner_assume.json
}

data "aws_iam_policy_document" "migration_runner" {
  statement {
    sid       = "StartFixedMigrationBroker"
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.migration.arn]
  }
}

resource "aws_iam_role_policy" "migration_runner" {
  name   = "start-fixed-migration"
  role   = aws_iam_role.migration_runner.id
  policy = data.aws_iam_policy_document.migration_runner.json
}

locals {
  qualification_secret_policy_contract = {
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyQualificationWritesOutsideQualifier"
      Effect    = "Deny"
      Principal = { AWS = "*" }
      Action = [
        "secretsmanager:DeleteResourcePolicy",
        "secretsmanager:DeleteSecret",
        "secretsmanager:PutResourcePolicy",
        "secretsmanager:PutSecretValue",
        "secretsmanager:RotateSecret",
        "secretsmanager:UpdateSecret",
        "secretsmanager:UpdateSecretVersionStage",
      ]
      Resource = aws_secretsmanager_secret.qualification.arn
      Condition = {
        ArnNotEquals = {
          "aws:PrincipalArn" = aws_iam_role.qualifier.arn
        }
      }
    }]
  }
}

resource "aws_secretsmanager_secret_policy" "qualification" {
  secret_arn          = aws_secretsmanager_secret.qualification.arn
  policy              = jsonencode(local.qualification_secret_policy_contract)
  block_public_policy = true
}

data "aws_iam_policy_document" "deployment_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.deployment_principal_arn]
    }
  }
}

resource "aws_iam_role" "deployment" {
  name               = "${local.name}-deployment"
  assume_role_policy = data.aws_iam_policy_document.deployment_assume.json
}

data "aws_iam_policy_document" "deployment" {
  statement {
    sid       = "AuthorizeECR"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "PublishImages"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [for repository in aws_ecr_repository.runtime : repository.arn]
  }
  statement {
    sid       = "ReadApprovedTaskDefinitions"
    actions   = ["ecs:DescribeTaskDefinition"]
    resources = [aws_ecs_task_definition.web.arn, aws_ecs_task_definition.api.arn, aws_ecs_task_definition.worker.arn]
  }
  statement {
    sid       = "ReadReleaseServices"
    actions   = ["ecs:DescribeServices"]
    resources = [aws_ecs_service.web.id, aws_ecs_service.api.id, aws_ecs_service.worker.id]
  }
}

resource "aws_iam_role_policy" "deployment" {
  name   = "release"
  role   = aws_iam_role.deployment.id
  policy = data.aws_iam_policy_document.deployment.json
}
