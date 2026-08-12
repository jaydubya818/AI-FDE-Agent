resource "aws_kms_key" "data" {
  description             = "${local.name} evidence, database, and secret encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "data" {
  name          = "alias/${local.name}-data"
  target_key_id = aws_kms_key.data.key_id
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
  versioning_configuration { status = "Disabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.data.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
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
  identifier                    = local.name
  engine                        = "postgres"
  instance_class                = var.database_instance_class
  allocated_storage             = 30
  max_allocated_storage         = 100
  storage_type                  = "gp3"
  storage_encrypted             = true
  kms_key_id                    = aws_kms_key.data.arn
  db_name                       = "ai_fde"
  username                      = "ai_fde_owner"
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.data.key_id
  multi_az                      = var.database_multi_az
  publicly_accessible           = false
  db_subnet_group_name          = aws_db_subnet_group.main.name
  vpc_security_group_ids        = [aws_security_group.database.id]
  parameter_group_name          = aws_db_parameter_group.postgres.name
  backup_retention_period       = 7
  backup_window                 = "08:00-09:00"
  maintenance_window            = "sun:09:00-sun:10:00"
  auto_minor_version_upgrade    = true
  copy_tags_to_snapshot         = true
  deletion_protection           = true
  skip_final_snapshot           = false
  final_snapshot_identifier     = "${local.name}-final"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret" "runtime" {
  for_each                = toset(["api", "worker", "migration"])
  name                    = "${local.name}/${each.key}"
  description             = "Populate the ${each.key} runtime secret out of band"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30
}
