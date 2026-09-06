locals {
  alarm_actions    = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]
  metric_namespace = "AI-FDE/${var.environment}"
}

resource "aws_cloudwatch_log_group" "mission_control_integration" {
  name              = "/integration/${local.name}/mission-control"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_metric_filter" "api_5xx" {
  name           = "${local.name}-api-5xx"
  log_group_name = aws_cloudwatch_log_group.runtime["api"].name
  pattern        = "{ $.event = \"http.request.completed\" && $.status_code >= 500 }"

  metric_transformation {
    name          = "Api5xx"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "auth_denied" {
  name           = "${local.name}-auth-denied"
  log_group_name = aws_cloudwatch_log_group.runtime["api"].name
  pattern        = "{ $.event = \"auth.denied\" }"

  metric_transformation {
    name          = "AuthDenied"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "api_dependency_failed" {
  name           = "${local.name}-api-dependency-failed"
  log_group_name = aws_cloudwatch_log_group.runtime["api"].name
  pattern        = "{ $.event = \"workflow.dependency_failed\" }"

  metric_transformation {
    name          = "WorkflowDependencyFailed"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "worker_job_failed" {
  name           = "${local.name}-worker-job-failed"
  log_group_name = aws_cloudwatch_log_group.runtime["worker"].name
  pattern        = "{ $.event = \"workflow.job.failed\" }"

  metric_transformation {
    name          = "WorkflowJobFailed"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "worker_dependency_failed" {
  name           = "${local.name}-worker-dependency-failed"
  log_group_name = aws_cloudwatch_log_group.runtime["worker"].name
  pattern        = "{ $.event = \"workflow.dependency_failed\" }"

  metric_transformation {
    name          = "WorkflowDependencyFailed"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "mission_control_ingestion_failed" {
  name           = "${local.name}-mission-control-ingestion-failed"
  log_group_name = aws_cloudwatch_log_group.mission_control_integration.name
  pattern        = "{ $.event = \"mission_control.ingestion_failed\" }"

  metric_transformation {
    name          = "MissionControlIngestionFailed"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "target_unhealthy" {
  for_each = {
    web = aws_lb_target_group.web
    api = aws_lb_target_group.api
  }

  alarm_name          = "${local.name}-${each.key}-target-unhealthy"
  alarm_description   = "Owner: technical on-call. Page after two minutes with an unhealthy ${each.key} target; inspect deployment and readiness, then roll back if release-related."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = each.value.arn_suffix }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "runtime" {
  for_each = {
    load_balancer_5xx = {
      namespace           = "AWS/ApplicationELB"
      metric_name         = "HTTPCode_ELB_5XX_Count"
      dimensions          = { LoadBalancer = aws_lb.main.arn_suffix }
      threshold           = 5
      period              = 300
      evaluation_periods  = 2
      datapoints_to_alarm = 2
      alarm_description   = "Owner: technical on-call. Investigate sustained load-balancer failures and dependency health; roll back if release-related."
    }
    target_5xx = {
      namespace           = "AWS/ApplicationELB"
      metric_name         = "HTTPCode_Target_5XX_Count"
      dimensions          = { LoadBalancer = aws_lb.main.arn_suffix }
      threshold           = 5
      period              = 300
      evaluation_periods  = 2
      datapoints_to_alarm = 2
      alarm_description   = "Owner: application on-call. Investigate sustained web or API target failures using the release identity and metadata-only logs."
    }
    api_5xx = {
      namespace           = local.metric_namespace
      metric_name         = "Api5xx"
      dimensions          = {}
      threshold           = 5
      period              = 300
      evaluation_periods  = 2
      datapoints_to_alarm = 2
      alarm_description   = "Owner: application on-call. Inspect bounded failure codes and traces for sustained API 5xx responses."
    }
    repeated_auth_denials = {
      namespace           = local.metric_namespace
      metric_name         = "AuthDenied"
      dimensions          = {}
      threshold           = 5
      period              = 300
      evaluation_periods  = 2
      datapoints_to_alarm = 2
      alarm_description   = "Owner: security on-call. Review repeated 401/403 denial metadata, identity provider health, and abuse indicators without logging credentials."
    }
    workflow_dependency_failure = {
      namespace           = local.metric_namespace
      metric_name         = "WorkflowDependencyFailed"
      dimensions          = {}
      threshold           = 1
      period              = 300
      evaluation_periods  = 1
      datapoints_to_alarm = 1
      alarm_description   = "Owner: application on-call. Stop affected work, inspect the bounded failure code and queue state, and retry only after dependency recovery."
    }
    workflow_job_failure = {
      namespace           = local.metric_namespace
      metric_name         = "WorkflowJobFailed"
      dimensions          = {}
      threshold           = 1
      period              = 300
      evaluation_periods  = 1
      datapoints_to_alarm = 1
      alarm_description   = "Owner: application on-call. Inspect the bounded job failure code and evidence state; retry only when policy permits and the lease is no longer active."
    }
    mission_control_ingestion_failure = {
      namespace           = local.metric_namespace
      metric_name         = "MissionControlIngestionFailed"
      dimensions          = {}
      threshold           = 1
      period              = 300
      evaluation_periods  = 1
      datapoints_to_alarm = 1
      alarm_description   = "Owner: integration on-call. Keep the package immutable, inspect the safe failure class, and retry the pull only with the same idempotency identity."
    }
  }

  alarm_name          = "${local.name}-${replace(each.key, "_", "-")}"
  alarm_description   = each.value.alarm_description
  namespace           = each.value.namespace
  metric_name         = each.value.metric_name
  dimensions          = each.value.dimensions
  statistic           = "Sum"
  period              = each.value.period
  evaluation_periods  = each.value.evaluation_periods
  datapoints_to_alarm = each.value.datapoints_to_alarm
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_db_event_subscription" "backup_and_recovery" {
  count = var.backup_event_topic_arn == null ? 0 : 1

  name             = "${local.name}-backup-and-recovery"
  sns_topic        = var.backup_event_topic_arn
  source_type      = "db-instance"
  source_ids       = [aws_db_instance.postgres.identifier]
  event_categories = ["backup", "failure", "recovery"]
  enabled          = true
}

resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${local.name}-operations"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "alarm"
        x      = 0
        y      = 0
        width  = 24
        height = 6
        properties = {
          title = "Actionable alarms"
          alarms = concat(
            values(aws_cloudwatch_metric_alarm.target_unhealthy)[*].arn,
            values(aws_cloudwatch_metric_alarm.runtime)[*].arn,
          )
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Availability and 5xx"
          region = var.aws_region
          stat   = "Sum"
          period = 300
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", aws_lb.main.arn_suffix],
            [".", "HTTPCode_Target_5XX_Count", ".", "."],
            ["AWS/ApplicationELB", "UnHealthyHostCount", "LoadBalancer", aws_lb.main.arn_suffix, "TargetGroup", aws_lb_target_group.web.arn_suffix, { stat = "Maximum" }],
            [".", ".", ".", ".", ".", aws_lb_target_group.api.arn_suffix, { stat = "Maximum" }],
            [local.metric_namespace, "Api5xx"],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Trust-boundary failures"
          region = var.aws_region
          stat   = "Sum"
          period = 300
          metrics = [
            [local.metric_namespace, "AuthDenied"],
            [".", "WorkflowJobFailed"],
            [".", "WorkflowDependencyFailed"],
            [".", "MissionControlIngestionFailed"],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 24
        height = 6
        properties = {
          title  = "ECS saturation"
          region = var.aws_region
          stat   = "Average"
          period = 300
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", "web"],
            [".", "MemoryUtilization", ".", ".", ".", "web"],
            [".", "CPUUtilization", ".", ".", ".", "api"],
            [".", "MemoryUtilization", ".", ".", ".", "api"],
            [".", "CPUUtilization", ".", ".", ".", "worker"],
            [".", "MemoryUtilization", ".", ".", ".", "worker"],
          ]
        }
      },
    ]
  })
}
