locals {
  common_python_environment = concat([
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
    { name = "AI_FDE_S3_REGION", value = var.aws_region },
    { name = "AI_FDE_S3_USE_WORKLOAD_IDENTITY", value = "true" },
    { name = "AI_FDE_EXTRACTION_PROVIDER", value = "bedrock" },
    { name = "AI_FDE_BEDROCK_MODEL_ID", value = var.bedrock_model_id },
    { name = "AI_FDE_BEDROCK_REGION", value = var.aws_region },
    { name = "AI_FDE_WORKER_LEASE_SECONDS", value = "300" },
    { name = "AI_FDE_SANITIZED_DATA_ENABLED", value = tostring(var.sanitized_data_enabled) },
    ], var.deployment_validation_id == null ? [] : [
    { name = "AI_FDE_DEPLOYMENT_VALIDATION_ID", value = var.deployment_validation_id },
  ])
  api_secrets = [
    {
      name      = "AI_FDE_DATABASE_URL"
      valueFrom = "${aws_secretsmanager_secret.runtime["api"].arn}:AI_FDE_DATABASE_URL::"
    },
    {
      name      = "AI_FDE_OIDC_CLIENT_SECRET"
      valueFrom = "${aws_secretsmanager_secret.runtime["api"].arn}:AI_FDE_OIDC_CLIENT_SECRET::"
    },
  ]
  worker_secrets = [{
    name      = "AI_FDE_DATABASE_URL"
    valueFrom = "${aws_secretsmanager_secret.runtime["worker"].arn}:AI_FDE_DATABASE_URL::"
  }]
  migration_secrets = [{
    name      = "AI_FDE_MIGRATION_DATABASE_URL"
    valueFrom = "${aws_secretsmanager_secret.runtime["migration"].arn}:AI_FDE_MIGRATION_DATABASE_URL::"
    }, {
    name      = "AI_FDE_APP_DATABASE_PASSWORD"
    valueFrom = "${aws_secretsmanager_secret.runtime["migration"].arn}:AI_FDE_APP_DATABASE_PASSWORD::"
  }]
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
    path                = "/api/health"
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
    environment = concat(local.common_python_environment, [
      { name = "AI_FDE_RUNTIME_ROLE", value = "api" },
    ])
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
      condition     = !var.sanitized_data_enabled || var.deployment_validation_id != null
      error_message = "Sanitized data requires a signed deployment validation identifier."
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
    environment = concat(local.common_python_environment, [
      { name = "AI_FDE_RUNTIME_ROLE", value = "worker" },
    ])
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
    environment = concat(local.common_python_environment, [
      { name = "AI_FDE_RUNTIME_ROLE", value = "migration" },
    ])
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
    security_groups  = [aws_security_group.tasks.id]
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
    security_groups  = [aws_security_group.tasks.id]
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
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
  }
}
