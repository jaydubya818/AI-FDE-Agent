locals {
  migration_state_machine_name = "${local.name}-migration-broker"
  migration_state_machine_arn  = "arn:${data.aws_partition.current.partition}:states:${var.aws_region}:${data.aws_caller_identity.current.account_id}:stateMachine:${local.migration_state_machine_name}"
  migration_task_arn_pattern   = "arn:${data.aws_partition.current.partition}:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task/${aws_ecs_cluster.main.name}/*"
  step_functions_ecs_rule_arn  = "arn:${data.aws_partition.current.partition}:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForECSTaskRule"
}

data "aws_iam_policy_document" "migration_broker_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [local.migration_state_machine_arn]
    }
  }
}

resource "aws_iam_role" "migration_broker" {
  name               = "${local.name}-migration-broker"
  assume_role_policy = data.aws_iam_policy_document.migration_broker_assume.json
}

data "aws_iam_policy_document" "migration_broker" {
  statement {
    sid       = "RunExactMigrationRevision"
    actions   = ["ecs:RunTask"]
    resources = [aws_ecs_task_definition.migration.arn]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
    condition {
      test     = "ArnEquals"
      variable = "ecs:task-definition"
      values   = [aws_ecs_task_definition.migration.arn]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "ecs:subnet"
      values   = aws_subnet.private[*].id
    }
    # ECS has no RunTask condition keys for security groups or launch type. Those values are
    # immutable, caller-inaccessible constants in the state machine definition below.
    condition {
      test     = "Bool"
      variable = "ecs:auto-assign-public-ip"
      values   = ["false"]
    }
    condition {
      test     = "Bool"
      variable = "ecs:enable-execute-command"
      values   = ["false"]
    }
  }

  statement {
    sid       = "ObserveOnlyBrokeredMigrationTasks"
    actions   = ["ecs:DescribeTasks", "ecs:StopTask"]
    resources = [local.migration_task_arn_pattern]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
  }

  statement {
    sid       = "PassOnlyMigrationRoles"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution["migration"].arn, aws_iam_role.task["migration"].arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid = "ManageStepFunctionsEcsCompletionRule"
    actions = [
      "events:DescribeRule",
      "events:PutRule",
      "events:PutTargets",
    ]
    resources = [local.step_functions_ecs_rule_arn]
  }
}

resource "aws_iam_role_policy" "migration_broker" {
  name   = "run-fixed-migration"
  role   = aws_iam_role.migration_broker.id
  policy = data.aws_iam_policy_document.migration_broker.json
}

resource "aws_sfn_state_machine" "migration" {
  name     = local.migration_state_machine_name
  role_arn = aws_iam_role.migration_broker.arn
  type     = "STANDARD"

  definition = jsonencode({
    Comment = "Run the exact Terraform-owned migration revision with a fixed private network boundary."
    StartAt = "RunExactMigration"
    States = {
      RunExactMigration = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::ecs:runTask.sync"
        Parameters = {
          Cluster              = aws_ecs_cluster.main.arn
          TaskDefinition       = aws_ecs_task_definition.migration.arn
          LaunchType           = "FARGATE"
          EnableExecuteCommand = false
          NetworkConfiguration = {
            AwsvpcConfiguration = {
              Subnets        = sort(aws_subnet.private[*].id)
              SecurityGroups = [aws_security_group.migration_tasks.id]
              AssignPublicIp = "DISABLED"
            }
          }
        }
        TimeoutSeconds = 1800
        ResultPath     = "$.migration_task"
        Next           = "VerifyMigrationExitCode"
      }
      VerifyMigrationExitCode = {
        Type = "Choice"
        Choices = [{
          Variable      = "$.migration_task.Containers[0].ExitCode"
          NumericEquals = 0
          Next          = "MigrationSucceeded"
        }]
        Default = "MigrationFailed"
      }
      MigrationSucceeded = {
        Type = "Succeed"
      }
      MigrationFailed = {
        Type  = "Fail"
        Error = "MigrationContainerFailed"
        Cause = "The fixed migration task stopped without a zero container exit code."
      }
    }
  })
}
