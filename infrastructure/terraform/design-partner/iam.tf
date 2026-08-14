locals {
  runtime_names = toset(["web", "api", "worker", "migration"])
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
    resources = [each.value.arn]
  }
  statement {
    sid       = "DecryptRuntimeSecret"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.data.arn]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  for_each = data.aws_iam_policy_document.execution_secrets
  name     = "runtime-secret"
  role     = aws_iam_role.execution[each.key].id
  policy   = each.value.json
}

resource "aws_iam_role" "task" {
  for_each           = local.runtime_names
  name               = "${local.name}-${each.key}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "evidence_access" {
  statement {
    sid       = "ListEvidencePrefix"
    actions   = ["s3:GetBucketLocation", "s3:ListBucket"]
    resources = [aws_s3_bucket.evidence.arn]
  }
  statement {
    sid = "ManageEvidenceObjects"
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
  }
  statement {
    sid = "UseEvidenceKey"
    actions = [
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.data.arn]
  }
}

resource "aws_iam_role_policy" "api_evidence" {
  name   = "evidence-objects"
  role   = aws_iam_role.task["api"].id
  policy = data.aws_iam_policy_document.evidence_access.json
}

resource "aws_iam_role_policy" "worker_evidence" {
  name   = "evidence-objects"
  role   = aws_iam_role.task["worker"].id
  policy = data.aws_iam_policy_document.evidence_access.json
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
    sid = "ReleaseTasks"
    actions = [
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:RegisterTaskDefinition",
      "ecs:RunTask",
      "ecs:UpdateService",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "PassRuntimeRoles"
    actions   = ["iam:PassRole"]
    resources = concat(values(aws_iam_role.execution)[*].arn, values(aws_iam_role.task)[*].arn)
  }
}

resource "aws_iam_role_policy" "deployment" {
  name   = "release"
  role   = aws_iam_role.deployment.id
  policy = data.aws_iam_policy_document.deployment.json
}
