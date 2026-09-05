resource "aws_kms_key" "data" {
  description             = "${local.name} database, secret, and container image encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "data" {
  name          = "alias/${local.name}-data"
  target_key_id = aws_kms_key.data.key_id
}

resource "aws_kms_key" "evidence" {
  description             = "${local.name} evidence object encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "evidence" {
  name          = "alias/${local.name}-evidence"
  target_key_id = aws_kms_key.evidence.key_id
}

resource "aws_kms_key" "evidence_signing" {
  description              = "${local.name} asymmetric production qualification evidence signer"
  deletion_window_in_days  = 30
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "RSA_3072"
}

resource "aws_kms_alias" "evidence_signing" {
  name          = "alias/${local.name}-qualification-evidence-signing"
  target_key_id = aws_kms_key.evidence_signing.key_id
}

data "aws_kms_public_key" "evidence_signing" {
  key_id = aws_kms_key.evidence_signing.key_id
}

resource "aws_s3_bucket" "evidence" {
  bucket        = "${local.name}-evidence-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.evidence.arn
      sse_algorithm     = "aws:kms"
    }
    # S3 Bucket Keys use the bucket ARN, rather than each object ARN, as the
    # KMS encryption context. The evidence role policies pin that exact value.
    bucket_key_enabled = true
  }
}

data "aws_iam_policy_document" "evidence_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.evidence.arn,
      "${aws_s3_bucket.evidence.arn}/*",
    ]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DenyMissingSSEKMS"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "Null"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = ["true"]
    }
  }

  statement {
    sid       = "DenyWrongSSEAlgorithm"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }

  statement {
    sid       = "DenyWrongKMSKey"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [aws_kms_key.evidence.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  policy = data.aws_iam_policy_document.evidence_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.evidence]
}

resource "aws_s3_bucket_lifecycle_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  depends_on = [aws_s3_bucket_versioning.evidence]

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }

  rule {
    id     = "expire-noncurrent-evidence"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.evidence_noncurrent_retention_days
    }

    expiration {
      expired_object_delete_marker = true
    }
  }
}

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "postgres" {
  name   = "${local.name}-postgres16"
  family = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_instance" "postgres" {
  identifier                          = local.name
  engine                              = "postgres"
  instance_class                      = var.database_instance_class
  allocated_storage                   = 30
  max_allocated_storage               = 100
  storage_type                        = "gp3"
  storage_encrypted                   = true
  kms_key_id                          = aws_kms_key.data.arn
  db_name                             = "ai_fde"
  username                            = "ai_fde_owner"
  manage_master_user_password         = true
  iam_database_authentication_enabled = true
  master_user_secret_kms_key_id       = aws_kms_key.data.key_id
  multi_az                            = var.database_multi_az
  publicly_accessible                 = false
  db_subnet_group_name                = aws_db_subnet_group.main.name
  vpc_security_group_ids              = [aws_security_group.database.id]
  parameter_group_name                = aws_db_parameter_group.postgres.name
  backup_retention_period             = 7
  backup_window                       = "08:00-09:00"
  maintenance_window                  = "sun:09:00-sun:10:00"
  auto_minor_version_upgrade          = true
  copy_tags_to_snapshot               = true
  deletion_protection                 = true
  skip_final_snapshot                 = false
  final_snapshot_identifier           = "${local.name}-final"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret" "runtime" {
  for_each                = toset(["api", "migration"])
  name                    = "${local.name}/${each.key}"
  description             = "Populate the ${each.key} runtime secret out of band"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30
}

resource "aws_secretsmanager_secret" "qualification" {
  name                    = "${local.name}/qualification"
  description             = "Immutable deployment qualification versions written only by the qualifier role"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30
}
