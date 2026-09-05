data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  name = "${var.project_name}-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = local.name }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = local.name }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.azs[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = false
  tags                    = { Name = "${local.name}-public-${count.index + 1}" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  tags              = { Name = "${local.name}-private-${count.index + 1}" }
}

resource "aws_subnet" "worker_private" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.azs[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index + 20)
  map_public_ip_on_launch = false
  tags                    = { Name = "${local.name}-worker-private-${count.index + 1}" }
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${local.name}-nat" }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  depends_on    = [aws_internet_gateway.main]
  tags          = { Name = local.name }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
  tags = { Name = "${local.name}-private" }
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table" "worker_private" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-worker-private-no-nat" }
}

resource "aws_route_table_association" "worker_private" {
  count          = 2
  subnet_id      = aws_subnet.worker_private[count.index].id
  route_table_id = aws_route_table.worker_private.id
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Public HTTPS ingress to the application load balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP redirect"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Web targets"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "API targets"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
}

resource "aws_security_group" "web_tasks" {
  name        = "${local.name}-web-tasks"
  description = "Private web tasks; ingress only from the ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Web from ALB"
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "HTTPS dependencies through NAT"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "api_tasks" {
  name        = "${local.name}-api-tasks"
  description = "Private API tasks with ALB ingress and bounded dependency egress"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "API from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "PostgreSQL within the VPC"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "HTTPS dependencies through NAT"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "worker_tasks" {
  name        = "${local.name}-worker-tasks"
  description = "Private worker tasks with no ingress and bounded dependency egress"
  vpc_id      = aws_vpc.main.id

  egress = []
}

resource "aws_security_group" "migration_tasks" {
  name        = "${local.name}-migration-tasks"
  description = "Private migration tasks with no ingress and bounded dependency egress"
  vpc_id      = aws_vpc.main.id

  egress = []
}

resource "aws_security_group" "database" {
  name        = "${local.name}-database"
  description = "PostgreSQL ingress only from private application tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "PostgreSQL TLS"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    security_groups = [
      aws_security_group.api_tasks.id,
      aws_security_group.worker_tasks.id,
      aws_security_group.migration_tasks.id,
    ]
  }
}

resource "aws_security_group" "private_endpoints" {
  name                   = "${local.name}-private-endpoints"
  description            = "TLS ingress only from the four ECS runtime security groups"
  vpc_id                 = aws_vpc.main.id
  revoke_rules_on_delete = true
  egress                 = []
}

resource "aws_vpc_security_group_ingress_rule" "private_endpoint_https" {
  for_each = {
    web       = aws_security_group.web_tasks.id
    api       = aws_security_group.api_tasks.id
    worker    = aws_security_group.worker_tasks.id
    migration = aws_security_group.migration_tasks.id
  }

  security_group_id            = aws_security_group.private_endpoints.id
  referenced_security_group_id = each.value
  description                  = "HTTPS from ${each.key} tasks"
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_security_group_egress_rule" "worker_database" {
  security_group_id            = aws_security_group.worker_tasks.id
  referenced_security_group_id = aws_security_group.database.id
  description                  = "PostgreSQL only to the RDS security group"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "migration_database" {
  security_group_id            = aws_security_group.migration_tasks.id
  referenced_security_group_id = aws_security_group.database.id
  description                  = "PostgreSQL only to the RDS security group"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "worker_private_endpoints" {
  security_group_id            = aws_security_group.worker_tasks.id
  referenced_security_group_id = aws_security_group.private_endpoints.id
  description                  = "HTTPS only to approved interface endpoints"
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_security_group_egress_rule" "migration_private_endpoints" {
  security_group_id            = aws_security_group.migration_tasks.id
  referenced_security_group_id = aws_security_group.private_endpoints.id
  description                  = "HTTPS only to approved interface endpoints"
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id, aws_route_table.worker_private.id]
  policy            = local.s3_endpoint_policy
}

resource "aws_vpc_security_group_egress_rule" "worker_s3" {
  security_group_id = aws_security_group.worker_tasks.id
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  description       = "HTTPS only through the regional S3 gateway endpoint"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "migration_s3" {
  security_group_id = aws_security_group.migration_tasks.id
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  description       = "HTTPS only through the regional S3 gateway endpoint"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "worker_dns_udp" {
  security_group_id = aws_security_group.worker_tasks.id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  description       = "DNS only to the VPC resolver"
  ip_protocol       = "udp"
  from_port         = 53
  to_port           = 53
}

resource "aws_vpc_security_group_egress_rule" "worker_dns_tcp" {
  security_group_id = aws_security_group.worker_tasks.id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  description       = "Large DNS responses only to the VPC resolver"
  ip_protocol       = "tcp"
  from_port         = 53
  to_port           = 53
}

resource "aws_vpc_security_group_egress_rule" "migration_dns_udp" {
  security_group_id = aws_security_group.migration_tasks.id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  description       = "DNS only to the VPC resolver"
  ip_protocol       = "udp"
  from_port         = 53
  to_port           = 53
}

resource "aws_vpc_security_group_egress_rule" "migration_dns_tcp" {
  security_group_id = aws_security_group.migration_tasks.id
  cidr_ipv4         = "${cidrhost(var.vpc_cidr, 2)}/32"
  description       = "Large DNS responses only to the VPC resolver"
  ip_protocol       = "tcp"
  from_port         = 53
  to_port           = 53
}

locals {
  s3_endpoint_policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Sid       = "APIEvidenceBucketLocation"
          Effect    = "Allow"
          Principal = "*"
          Action    = ["s3:GetBucketLocation"]
          Resource  = aws_s3_bucket.evidence.arn
          Condition = {
            ArnEquals = {
              "aws:PrincipalArn" = aws_iam_role.task["api"].arn
            }
          }
        },
        {
          Sid       = "APIEvidenceBucket"
          Effect    = "Allow"
          Principal = "*"
          Action    = ["s3:ListBucket", "s3:ListBucketVersions"]
          Resource  = aws_s3_bucket.evidence.arn
          Condition = {
            ArnEquals = {
              "aws:PrincipalArn" = aws_iam_role.task["api"].arn
            }
            StringLike = {
              "s3:prefix" = ["engagements/*/evidence/*"]
            }
          }
        },
        {
          Sid       = "APIEvidenceObjects"
          Effect    = "Allow"
          Principal = "*"
          Action = [
            "s3:DeleteObject",
            "s3:DeleteObjectVersion",
            "s3:GetObject",
            "s3:GetObjectVersion",
            "s3:PutObject",
          ]
          Resource = "${aws_s3_bucket.evidence.arn}/engagements/*/evidence/*"
          Condition = {
            ArnEquals = {
              "aws:PrincipalArn" = aws_iam_role.task["api"].arn
            }
          }
        },
      ],
      var.worker_engagement_id == null ? [] : [
        {
          Sid       = "WorkerEvidenceObjects"
          Effect    = "Allow"
          Principal = "*"
          Action    = ["s3:GetObject", "s3:GetObjectVersion"]
          Resource  = "${aws_s3_bucket.evidence.arn}/engagements/${coalesce(var.worker_engagement_id, "disabled")}/evidence/*"
          Condition = {
            ArnEquals = {
              "aws:PrincipalArn" = aws_iam_role.task["worker"].arn
            }
          }
        },
      ],
      [
        {
          # Fargate downloads ECR layers from regional S3 pre-signed URLs, so
          # this AWS-owned bucket cannot be principal-scoped like evidence.
          Sid       = "ECRImageLayers"
          Effect    = "Allow"
          Principal = "*"
          Action    = ["s3:GetObject"]
          Resource  = "arn:${data.aws_partition.current.partition}:s3:::prod-${var.aws_region}-starport-layer-bucket/*"
        },
      ],
    )
  })
  interface_endpoint_policies = {
    secretsmanager = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Effect    = "Allow"
        Principal = "*"
        Action    = ["secretsmanager:DescribeSecret", "secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
        Resource = concat(
          values(aws_secretsmanager_secret.runtime)[*].arn,
          [aws_secretsmanager_secret.qualification.arn],
          local.package_retrieval_target_secret_arns,
        )
      }]
    })
    bedrock-runtime = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Effect    = "Allow"
        Principal = "*"
        Action    = ["bedrock:InvokeModel"]
        Resource  = [var.bedrock_model_arn]
      }]
    })
    "ecr.api" = jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Effect    = "Allow"
          Principal = "*"
          Action    = ["ecr:GetAuthorizationToken"]
          Resource  = "*"
        },
        {
          Effect    = "Allow"
          Principal = "*"
          Action    = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
          Resource  = values(aws_ecr_repository.runtime)[*].arn
        },
      ]
    })
    "ecr.dkr" = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Effect    = "Allow"
        Principal = "*"
        Action    = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
        Resource  = values(aws_ecr_repository.runtime)[*].arn
      }]
    })
    logs = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Effect    = "Allow"
        Principal = "*"
        Action    = ["logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"]
        Resource  = [for group in aws_cloudwatch_log_group.runtime : "${group.arn}:*"]
      }]
    })
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each = local.interface_endpoint_policies

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.private_endpoints.id]
  policy              = each.value
}
