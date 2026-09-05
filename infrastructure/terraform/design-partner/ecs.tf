locals {
  rds_ca_bundle_path   = "/opt/ai-fde/certs/aws-rds-global-bundle.pem"
  rds_ca_bundle_sha256 = "sha256:e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
  common_python_environment = [
    { name = "AI_FDE_ENV", value = "production" },
    { name = "AI_FDE_AUTH_MODE", value = "oidc" },
    { name = "AI_FDE_ALLOWED_ORIGINS", value = jsonencode(["https://${var.domain_name}"]) },
    { name = "AI_FDE_COCKPIT_URL", value = "https://${var.domain_name}" },
    { name = "AI_FDE_OIDC_ISSUER_URL", value = var.oidc_issuer_url },
    { name = "AI_FDE_OIDC_CLIENT_ID", value = var.oidc_client_id },
    { name = "AI_FDE_OIDC_REDIRECT_URI", value = "https://${var.domain_name}/api/auth/callback" },
    { name = "AI_FDE_OIDC_ALLOWED_EMAILS", value = jsonencode(var.oidc_allowed_emails) },
    { name = "AI_FDE_WORKER_OPERATOR_ID", value = var.worker_operator_id },
    { name = "AI_FDE_S3_BUCKET", value = aws_s3_bucket.evidence.id },
    { name = "AI_FDE_S3_KMS_KEY_ARN", value = aws_kms_key.evidence.arn },
    { name = "AI_FDE_S3_REGION", value = var.aws_region },
    { name = "AI_FDE_S3_USE_WORKLOAD_IDENTITY", value = "true" },
    { name = "AI_FDE_EXTRACTION_PROVIDER", value = "bedrock" },
    { name = "AI_FDE_BEDROCK_MODEL_ID", value = var.bedrock_model_id },
    { name = "AI_FDE_BEDROCK_REGION", value = var.aws_region },
    { name = "AI_FDE_BEDROCK_ALLOWED_DATA_CLASSIFICATIONS", value = jsonencode(sort(var.bedrock_allowed_data_classifications)) },
    { name = "AI_FDE_WORKER_LEASE_SECONDS", value = "300" },
    { name = "AI_FDE_SANITIZED_DATA_ENABLED", value = tostring(var.sanitized_data_enabled) },
    { name = "AI_FDE_RELEASE_REVISION", value = var.release_revision },
    { name = "AI_FDE_DEPLOYMENT_ID", value = var.deployment_id },
    { name = "AI_FDE_DEPLOYMENT_QUALIFICATION_MODE", value = var.deployment_qualification_mode },
    { name = "AI_FDE_DEPLOYMENT_QUALIFICATION_ROLE_ARN", value = aws_iam_role.qualifier.arn },
    { name = "AI_FDE_QUALIFICATION_SECRET_POLICY_SHA256", value = "sha256:${sha256(jsonencode(local.qualification_secret_policy_contract))}" },
    { name = "AI_FDE_RDS_CA_BUNDLE_PATH", value = local.rds_ca_bundle_path },
    { name = "AI_FDE_RDS_CA_BUNDLE_SHA256", value = local.rds_ca_bundle_sha256 },
    { name = "AI_FDE_EVIDENCE_SIGNING_PUBLIC_KEY_DER_B64", value = data.aws_kms_public_key.evidence_signing.public_key },
    { name = "AI_FDE_EVIDENCE_SIGNING_PUBLIC_KEY_B64_SHA256", value = "sha256:${sha256(data.aws_kms_public_key.evidence_signing.public_key)}" },
  ]
  active_qualification_environment = var.active_qualification_record_version_id == null ? [] : [
    { name = "AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD_VERSION_ID", value = var.active_qualification_record_version_id },
  ]
  pending_qualification_environment = var.pending_qualification_record_version_id == null ? [] : [
    { name = "AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD_VERSION_ID", value = var.pending_qualification_record_version_id },
  ]
  active_qualification_record_secret = var.active_qualification_record_version_id == null ? [] : [{
    name      = "AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD"
    valueFrom = "${aws_secretsmanager_secret.qualification.arn}:::${var.active_qualification_record_version_id}"
  }]
  pending_qualification_record_secret = var.pending_qualification_record_version_id == null ? [] : [{
    name      = "AI_FDE_DEPLOYMENT_QUALIFICATION_RECORD"
    valueFrom = "${aws_secretsmanager_secret.qualification.arn}:::${var.pending_qualification_record_version_id}"
  }]
  api_secrets = concat([
    {
      name      = "AI_FDE_DATABASE_URL"
      valueFrom = "${aws_secretsmanager_secret.runtime["api"].arn}:AI_FDE_DATABASE_URL::${var.api_runtime_secret_version_id}"
    },
    {
      name      = "AI_FDE_OIDC_CLIENT_SECRET"
      valueFrom = "${aws_secretsmanager_secret.runtime["api"].arn}:AI_FDE_OIDC_CLIENT_SECRET::${var.api_runtime_secret_version_id}"
    },
  ], local.active_qualification_record_secret)
  worker_secrets = local.active_qualification_record_secret
  migration_secrets = concat([{
    name      = "AI_FDE_MIGRATION_DATABASE_URL"
    valueFrom = "${aws_secretsmanager_secret.runtime["migration"].arn}:AI_FDE_MIGRATION_DATABASE_URL::${var.migration_runtime_secret_version_id}"
    }, {
    name      = "AI_FDE_APP_DATABASE_PASSWORD"
    valueFrom = "${aws_secretsmanager_secret.runtime["migration"].arn}:AI_FDE_APP_DATABASE_PASSWORD::${var.migration_runtime_secret_version_id}"
  }], local.pending_qualification_record_secret)
}

resource "aws_cloudwatch_log_group" "runtime" {
  for_each          = toset(["web", "api", "worker", "migration"])
  name              = "/ecs/${local.name}/${each.key}"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enhanced"
  }
}

resource "aws_lb" "main" {
  name                       = substr(local.name, 0, 32)
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.public[*].id
  drop_invalid_header_fields = true
  enable_deletion_protection = true
  idle_timeout               = 60
}

resource "aws_lb_target_group" "web" {
  name        = substr("${local.name}-web", 0, 32)
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path                = "/"
    matcher             = "200-399"
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_target_group" "api" {
  name        = substr("${local.name}-api", 0, 32)
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path                = "/api/ready"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
  condition {
    path_pattern { values = ["/api", "/api/*"] }
  }
}

resource "aws_route53_record" "app" {
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"
  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${local.name}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution["web"].arn
  task_role_arn            = aws_iam_role.task["web"].arn
  container_definitions = jsonencode([{
    name               = "web"
    image              = var.web_image
    essential          = true
    versionConsistency = "enabled"
    portMappings       = [{ containerPort = 3000, hostPort = 3000, protocol = "tcp" }]
    environment = [
      { name = "NODE_ENV", value = "production" },
      { name = "HOSTNAME", value = "0.0.0.0" },
      { name = "PORT", value = "3000" },
      { name = "AI_FDE_RELEASE_REVISION", value = var.release_revision },
      { name = "AI_FDE_DEPLOYMENT_ID", value = var.deployment_id },
      { name = "AI_FDE_DEPLOYMENT_QUALIFICATION_MODE", value = var.deployment_qualification_mode },
    ]
    readonlyRootFilesystem = false
    user                   = "10001"
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.runtime["web"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "web"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution["api"].arn
  task_role_arn            = aws_iam_role.task["api"].arn
  container_definitions = jsonencode([{
    name               = "api"
    image              = var.api_image
    essential          = true
    versionConsistency = "enabled"
    portMappings       = [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }]
    environment = concat(
      local.common_python_environment,
      local.active_qualification_environment,
      [{ name = "AI_FDE_RUNTIME_ROLE", value = "api" }],
      var.worker_engagement_id == null ? [] : [
        { name = "AI_FDE_WORKER_ENGAGEMENT_ID", value = var.worker_engagement_id },
      ],
    )
    secrets                = local.api_secrets
    readonlyRootFilesystem = true
    user                   = "10001"
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.runtime["api"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "api"
      }
    }
  }])

  lifecycle {
    precondition {
      condition     = !var.sanitized_data_enabled || var.active_qualification_record_version_id != null
      error_message = "Sanitized data requires the qualifier's exact immutable secret version."
    }
    precondition {
      condition = !var.sanitized_data_enabled || (
        var.pending_qualification_record_version_id == var.active_qualification_record_version_id
      )
      error_message = "Activation requires pending and active qualification versions to match exactly."
    }
  }
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution["worker"].arn
  task_role_arn            = aws_iam_role.task["worker"].arn
  container_definitions = jsonencode([{
    name               = "worker"
    image              = var.worker_image
    essential          = true
    versionConsistency = "enabled"
    environment = concat(
      local.common_python_environment,
      local.active_qualification_environment,
      [
        { name = "AI_FDE_RUNTIME_ROLE", value = "worker" },
        { name = "AI_FDE_DATABASE_AUTH_MODE", value = "rds-iam" },
        {
          name  = "AI_FDE_DATABASE_URL"
          value = "postgresql+psycopg://${local.worker_database_user}@${aws_db_instance.postgres.address}:${aws_db_instance.postgres.port}/${aws_db_instance.postgres.db_name}?sslmode=verify-full&sslrootcert=${local.rds_ca_bundle_path}"
        },
      ],
      var.worker_engagement_id == null ? [] : [
        { name = "AI_FDE_WORKER_ENGAGEMENT_ID", value = var.worker_engagement_id },
      ],
    )
    secrets                = local.worker_secrets
    readonlyRootFilesystem = true
    user                   = "10001"
    stopTimeout            = 120
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.runtime["worker"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "worker"
      }
    }
  }])

  lifecycle {
    precondition {
      condition     = !var.sanitized_data_enabled || var.worker_engagement_id != null
      error_message = "Sanitized data requires one exact worker_engagement_id evidence boundary."
    }
    precondition {
      condition     = startswith(local.worker_database_user, "ai_fde_worker_") && length(local.worker_database_user) == 26
      error_message = "The worker database login must be release-scoped."
    }
  }
}

resource "aws_ecs_task_definition" "migration" {
  family                   = "${local.name}-migration"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution["migration"].arn
  task_role_arn            = aws_iam_role.task["migration"].arn
  container_definitions = jsonencode([{
    name               = "migration"
    image              = var.api_image
    essential          = true
    versionConsistency = "enabled"
    command            = ["python", "scripts/bootstrap_production_database.py"]
    environment = concat(
      local.common_python_environment,
      local.pending_qualification_environment,
      [{ name = "AI_FDE_RUNTIME_ROLE", value = "migration" }],
      var.worker_engagement_id == null ? [] : [
        { name = "AI_FDE_WORKER_ENGAGEMENT_ID", value = var.worker_engagement_id },
      ],
    )
    secrets                = local.migration_secrets
    readonlyRootFilesystem = true
    user                   = "10001"
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.runtime["migration"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "migration"
      }
    }
  }])
}

resource "aws_ecs_service" "web" {
  name                              = "web"
  cluster                           = aws_ecs_cluster.main.id
  task_definition                   = aws_ecs_task_definition.web.arn
  desired_count                     = var.services_enabled ? 2 : 0
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 60
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    assign_public_ip = false
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.web_tasks.id]
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 3000
  }
  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_service" "api" {
  name                              = "api"
  cluster                           = aws_ecs_cluster.main.id
  task_definition                   = aws_ecs_task_definition.api.arn
  desired_count                     = var.services_enabled ? 2 : 0
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 60
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    assign_public_ip = false
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.api_tasks.id]
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener_rule.api]
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.services_enabled ? 1 : 0
  launch_type     = "FARGATE"
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    assign_public_ip = false
    subnets          = aws_subnet.worker_private[*].id
    security_groups  = [aws_security_group.worker_tasks.id]
  }
}
