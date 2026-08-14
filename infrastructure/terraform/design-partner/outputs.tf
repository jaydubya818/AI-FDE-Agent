output "application_url" {
  value = "https://${var.domain_name}"
}

output "runtime_secret_arns" {
  value       = { for name, secret in aws_secretsmanager_secret.runtime : name => secret.arn }
  description = "Populate only the per-role JSON keys listed in README.md before starting tasks."
}

output "rds_master_secret_arn" {
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
  description = "Bootstrap-only owner credential; applications use scoped roles in runtime secret."
  sensitive   = true
}

output "evidence_bucket" {
  value = aws_s3_bucket.evidence.id
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "private_subnets" {
  value = aws_subnet.private[*].id
}

output "task_security_group" {
  value = aws_security_group.tasks.id
}

output "deployment_role_arn" {
  value = aws_iam_role.deployment.arn
}

output "ecr_repositories" {
  value = { for name, repository in aws_ecr_repository.runtime : name => repository.repository_url }
}
