variable "project_name" {
  description = "Short lowercase name used in AWS resource names."
  type        = string
  default     = "ai-fde"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "design-partner"
}

variable "aws_region" {
  description = "Single AWS region for application and data processing."
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "domain_name" {
  description = "Public cockpit hostname."
  type        = string
}

variable "route53_zone_id" {
  description = "Route53 public hosted zone containing domain_name."
  type        = string
}

variable "acm_certificate_arn" {
  description = "Validated ACM certificate for domain_name."
  type        = string
}

variable "web_image" {
  description = "Immutable ECR web image URI including digest."
  type        = string
  validation {
    condition     = can(regex("^.+@sha256:[0-9a-f]{64}$", var.web_image))
    error_message = "web_image must end in an exact lowercase sha256 digest."
  }
}

variable "api_image" {
  description = "Immutable ECR API image URI including digest."
  type        = string
  validation {
    condition     = can(regex("^.+@sha256:[0-9a-f]{64}$", var.api_image))
    error_message = "api_image must end in an exact lowercase sha256 digest."
  }
}

variable "worker_image" {
  description = "Immutable ECR worker image URI including digest."
  type        = string
  validation {
    condition     = can(regex("^.+@sha256:[0-9a-f]{64}$", var.worker_image))
    error_message = "worker_image must end in an exact lowercase sha256 digest."
  }
}

variable "release_revision" {
  description = "Exact lowercase 40-character Git revision built into every runtime in this release."
  type        = string

  validation {
    condition = (
      can(regex("^[0-9a-f]{40}$", var.release_revision)) &&
      var.release_revision != "0000000000000000000000000000000000000000"
    )
    error_message = "release_revision must be a non-placeholder exact 40-character lowercase Git SHA."
  }
}

variable "deployment_id" {
  description = "Stable release/deployment record identifier propagated to every runtime."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{7,119}$", var.deployment_id))
    error_message = "deployment_id must be 8-120 lowercase letters, digits, dots, underscores, or hyphens."
  }
}

variable "deployment_qualification_mode" {
  description = "Informational release provenance; it never bypasses runtime authorization."
  type        = string
  default     = "controlled-design-partner"

  validation {
    condition     = var.deployment_qualification_mode == "controlled-design-partner"
    error_message = "This stack only supports controlled-design-partner qualification mode."
  }
}

variable "worker_operator_id" {
  description = "Stable UUID of the provisioned AI-FDE service operator."
  type        = string

  validation {
    condition = (
      can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.worker_operator_id)) &&
      var.worker_operator_id != "00000000-0000-0000-0000-000000000000"
    )
    error_message = "worker_operator_id must be a nonzero canonical lowercase UUID."
  }
}

variable "worker_engagement_id" {
  description = "Optional single engagement UUID whose evidence prefix the worker may read; required before sanitized data is enabled."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.worker_engagement_id == null ||
      (
        can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.worker_engagement_id)) &&
        var.worker_engagement_id != "00000000-0000-0000-0000-000000000000"
      )
    )
    error_message = "worker_engagement_id must be null or a nonzero canonical lowercase UUID."
  }
}

variable "bedrock_model_id" {
  description = "Evaluation-approved version-pinned regional foundation model ID."
  type        = string
}

variable "bedrock_model_arn" {
  description = "Exact ARN authorized for Bedrock model invocation."
  type        = string

  validation {
    condition = (
      can(regex("^arn:aws(|-us-gov|-cn|-iso|-iso-b):bedrock:[a-z0-9-]+::foundation-model/[A-Za-z0-9:.-]+$", var.bedrock_model_arn)) &&
      !strcontains(var.bedrock_model_arn, "*")
    )
    error_message = "bedrock_model_arn must be one exact regional accountless foundation-model ARN."
  }
}

variable "bedrock_allowed_data_classifications" {
  description = "Explicit data classifications permitted to leave the application boundary for Bedrock."
  type        = list(string)
  default     = ["PUBLIC", "INTERNAL"]

  validation {
    condition = (
      length(var.bedrock_allowed_data_classifications) > 0 &&
      length(var.bedrock_allowed_data_classifications) == length(toset(var.bedrock_allowed_data_classifications)) &&
      length(setsubtract(
        toset(var.bedrock_allowed_data_classifications),
        toset(["PUBLIC", "INTERNAL", "CONFIDENTIAL"]),
      )) == 0
    )
    error_message = "Bedrock classifications must be unique PUBLIC, INTERNAL, or explicitly enabled CONFIDENTIAL values; RESTRICTED is never allowed."
  }
}

variable "oidc_issuer_url" {
  description = "HTTPS Auth0 issuer URL including trailing slash."
  type        = string
  validation {
    condition     = startswith(var.oidc_issuer_url, "https://") && endswith(var.oidc_issuer_url, "/")
    error_message = "oidc_issuer_url must be HTTPS and include a trailing slash."
  }
}

variable "oidc_client_id" {
  description = "Auth0 Regular Web Application client ID."
  type        = string
}

variable "oidc_allowed_emails" {
  description = "Initial human operator allowlist."
  type        = list(string)

  validation {
    condition     = length(var.oidc_allowed_emails) > 0
    error_message = "At least one allowed operator email is required."
  }
}

variable "database_instance_class" {
  type    = string
  default = "db.t4g.small"
}

variable "database_multi_az" {
  description = "Must remain true before sanitized data is enabled."
  type        = bool
  default     = true

  validation {
    condition     = var.database_multi_az
    error_message = "The design-partner database must be Multi-AZ."
  }
}

variable "deployment_principal_arn" {
  description = "Existing federated CI/CD principal allowed to assume the deployment role."
  type        = string

  validation {
    condition     = can(regex("^arn:aws(|-us-gov|-cn|-iso|-iso-b):iam::[0-9]{12}:(role|user)/[A-Za-z0-9+=,.@_/-]+$", var.deployment_principal_arn)) && !strcontains(var.deployment_principal_arn, "*")
    error_message = "deployment_principal_arn must be one exact IAM role or user ARN, never root, STS, or a wildcard."
  }
}

variable "qualification_principal_arn" {
  description = "Existing federated security/release principal allowed to assume only the qualification role; must differ from deployment_principal_arn."
  type        = string

  validation {
    condition     = can(regex("^arn:aws(|-us-gov|-cn|-iso|-iso-b):iam::[0-9]{12}:(role|user)/[A-Za-z0-9+=,.@_/-]+$", var.qualification_principal_arn)) && !strcontains(var.qualification_principal_arn, "*")
    error_message = "qualification_principal_arn must be one exact IAM role or user ARN, never root, STS, or a wildcard."
  }
}

variable "evidence_principal_arn" {
  description = "Existing independent control principal allowed to assume the evidence-signing role."
  type        = string

  validation {
    condition     = can(regex("^arn:aws(|-us-gov|-cn|-iso|-iso-b):iam::[0-9]{12}:(role|user)/[A-Za-z0-9+=,.@_/-]+$", var.evidence_principal_arn)) && !strcontains(var.evidence_principal_arn, "*")
    error_message = "evidence_principal_arn must be one exact IAM role or user ARN, never root, STS, or a wildcard."
  }
}

variable "migration_principal_arn" {
  description = "Existing operations principal allowed only to start the Terraform-owned fixed migration broker."
  type        = string

  validation {
    condition     = can(regex("^arn:aws(|-us-gov|-cn|-iso|-iso-b):iam::[0-9]{12}:(role|user)/[A-Za-z0-9+=,.@_/-]+$", var.migration_principal_arn)) && !strcontains(var.migration_principal_arn, "*")
    error_message = "migration_principal_arn must be one exact IAM role or user ARN, never root, STS, or a wildcard."
  }
}

variable "prior_worker_task_role_arns" {
  description = "Sorted exact superseded worker role ARNs whose revocation the qualifier must prove."
  type        = list(string)

  validation {
    condition = (
      var.prior_worker_task_role_arns == sort(distinct(var.prior_worker_task_role_arns)) &&
      alltrue([
        for arn in var.prior_worker_task_role_arns :
        can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+$", arn)) && !strcontains(arn, "*")
      ])
    )
    error_message = "prior_worker_task_role_arns must be an explicitly empty or sorted unique list of exact IAM role ARNs."
  }
}

variable "package_retrieval_target_secret_arn" {
  description = "Optional existing same-region Secrets Manager ARN that the migration/admin task may update with the current Mission Control package-retrieval grant."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.package_retrieval_target_secret_arn == null ||
      can(regex("^arn:aws[a-z-]*:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+$", var.package_retrieval_target_secret_arn))
    )
    error_message = "package_retrieval_target_secret_arn must be null or an exact Secrets Manager secret ARN."
  }
}

variable "package_retrieval_target_kms_key_arn" {
  description = "Optional exact customer-managed KMS key ARN used by the package-retrieval target secret; leave null for the Secrets Manager AWS-managed key."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.package_retrieval_target_kms_key_arn == null ||
      can(regex("^arn:aws[a-z-]*:kms:[a-z0-9-]+:[0-9]{12}:key/[0-9a-fA-F-]{36}$", var.package_retrieval_target_kms_key_arn))
    )
    error_message = "package_retrieval_target_kms_key_arn must be null or an exact KMS key ARN."
  }
}

variable "sanitized_data_enabled" {
  description = "Keep false until an immutable qualification version exists; verify activation after changing this to true."
  type        = bool
  default     = false
}

variable "api_runtime_secret_version_id" {
  description = "Exact signed AWSCURRENT VersionId pinned into both API runtime-secret JSON-key selectors."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9-]{32,64}$", var.api_runtime_secret_version_id))
    error_message = "api_runtime_secret_version_id must be an exact 32-64 character Secrets Manager VersionId."
  }
}

variable "migration_runtime_secret_version_id" {
  description = "Exact signed AWSCURRENT VersionId pinned into both migration/owner runtime-secret JSON-key selectors."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9-]{32,64}$", var.migration_runtime_secret_version_id))
    error_message = "migration_runtime_secret_version_id must be an exact 32-64 character Secrets Manager VersionId."
  }
}

variable "pending_qualification_record_version_id" {
  description = "Candidate Secrets Manager VersionId injected only into the migration task for pre-activation database binding."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.pending_qualification_record_version_id == null ||
      can(regex("^[0-9a-f]{64}$", var.pending_qualification_record_version_id))
    )
    error_message = "pending_qualification_record_version_id must be null or the exact 64-character qualifier-emitted version."
  }
}

variable "active_qualification_record_version_id" {
  description = "Activated Secrets Manager VersionId injected only into API/worker services; set with sanitized_data_enabled after migration binding."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.active_qualification_record_version_id == null ||
      can(regex("^[0-9a-f]{64}$", var.active_qualification_record_version_id))
    )
    error_message = "active_qualification_record_version_id must be null or the exact 64-character qualifier-emitted version."
  }
}

variable "evidence_noncurrent_retention_days" {
  description = "Maximum retention for noncurrent evidence object versions before lifecycle expiry."
  type        = number
  default     = 30

  validation {
    condition     = var.evidence_noncurrent_retention_days >= 7 && var.evidence_noncurrent_retention_days <= 90
    error_message = "Noncurrent evidence retention must remain between 7 and 90 days."
  }
}

variable "alarm_topic_arn" {
  description = "Optional existing SNS topic ARN for actionable CloudWatch alarms and RDS recovery events."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.alarm_topic_arn == null ||
      can(regex("^arn:aws[a-z-]*:sns:[a-z0-9-]+:[0-9]{12}:[A-Za-z0-9_-]+$", var.alarm_topic_arn))
    )
    error_message = "alarm_topic_arn must be null or an SNS topic ARN."
  }
}

variable "backup_event_topic_arn" {
  description = "Optional existing non-paging SNS topic ARN for RDS backup, failure, and recovery events."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.backup_event_topic_arn == null ||
      can(regex("^arn:aws[a-z-]*:sns:[a-z0-9-]+:[0-9]{12}:[A-Za-z0-9_-]+$", var.backup_event_topic_arn))
    )
    error_message = "backup_event_topic_arn must be null or an SNS topic ARN."
  }
}

variable "services_enabled" {
  description = "Enable only after the runtime secret, migrations, and service worker exist."
  type        = bool
  default     = false
}
