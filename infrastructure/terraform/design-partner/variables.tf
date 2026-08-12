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
    condition     = strcontains(var.web_image, "@sha256:")
    error_message = "web_image must use an immutable digest."
  }
}

variable "api_image" {
  description = "Immutable ECR API image URI including digest."
  type        = string
  validation {
    condition     = strcontains(var.api_image, "@sha256:")
    error_message = "api_image must use an immutable digest."
  }
}

variable "worker_image" {
  description = "Immutable ECR worker image URI including digest."
  type        = string
  validation {
    condition     = strcontains(var.worker_image, "@sha256:")
    error_message = "worker_image must use an immutable digest."
  }
}

variable "worker_operator_id" {
  description = "Stable UUID of the provisioned AI-FDE service operator."
  type        = string
}

variable "bedrock_model_id" {
  description = "Evaluation-approved version-pinned Bedrock model or inference profile ID."
  type        = string
}

variable "bedrock_model_arn" {
  description = "Exact ARN authorized for Bedrock model invocation."
  type        = string
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
}

variable "sanitized_data_enabled" {
  description = "Keep false until the signed deployment validation is complete."
  type        = bool
  default     = false
}

variable "deployment_validation_id" {
  description = "Identifier emitted by verify_design_partner_readiness.py after a passing run."
  type        = string
  default     = null
  nullable    = true
}

variable "services_enabled" {
  description = "Enable only after the runtime secret, migrations, and service worker exist."
  type        = bool
  default     = false
}
