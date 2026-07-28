data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name = "${var.cluster_name}-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, var.availability_zone_count)

  private_subnets = [
    for index in range(var.availability_zone_count) :
    cidrsubnet(var.vpc_cidr, 4, index)
  ]
  public_subnets = [
    for index in range(var.availability_zone_count) :
    cidrsubnet(var.vpc_cidr, 8, index + 64)
  ]
  database_subnets = [
    for index in range(var.availability_zone_count) :
    cidrsubnet(var.vpc_cidr, 8, index + 96)
  ]

  tags = {
    Project     = "ml-platform-blueprint"
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  pod_identity_assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowEksPodIdentity"
      Effect = "Allow"
      Principal = {
        Service = "pods.eks.amazonaws.com"
      }
      Action = [
        "sts:AssumeRole",
        "sts:TagSession",
      ]
    }]
  })

  core_node_groups = {
    system = {
      instance_types = var.system_instance_types
      capacity_type  = "ON_DEMAND"
      min_size       = 2
      max_size       = 4
      desired_size   = 2
      labels = {
        "ml-platform.io/node-pool" = "system"
      }
    }
    cpu-ml = {
      instance_types = var.cpu_ml_instance_types
      capacity_type  = "SPOT"
      min_size       = 0
      max_size       = 10
      desired_size   = 1
      labels = {
        "ml-platform.io/node-pool" = "cpu-ml"
      }
    }
  }

  gpu_node_groups = var.enable_gpu_nodes ? {
    gpu-a10 = {
      instance_types = var.gpu_instance_types
      ami_type       = "AL2023_x86_64_NVIDIA"
      capacity_type  = "ON_DEMAND"
      min_size       = 0
      max_size       = 4
      desired_size   = 0
      labels = {
        "ml-platform.io/node-pool"   = "gpu"
        "ml-platform.io/accelerator" = "nvidia-a10"
      }
      taints = {
        nvidia = {
          key    = "nvidia.com/gpu"
          value  = "present"
          effect = "NO_SCHEDULE"
        }
      }
    }
  } : {}
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.21.0"

  name = local.name
  cidr = var.vpc_cidr
  azs  = local.azs

  private_subnets  = local.private_subnets
  public_subnets   = local.public_subnets
  database_subnets = local.database_subnets

  enable_nat_gateway     = true
  single_nat_gateway     = var.environment != "prod"
  one_nat_gateway_per_az = var.environment == "prod"
  enable_dns_hostnames   = true
  enable_dns_support     = true

  create_database_subnet_group = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
    "karpenter.sh/discovery"          = local.name
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "20.36.0"

  cluster_name                    = local.name
  cluster_version                 = var.kubernetes_version
  cluster_endpoint_private_access = true
  cluster_endpoint_public_access  = var.environment != "prod"
  cluster_enabled_log_types = [
    "api",
    "audit",
    "authenticator",
    "controllerManager",
    "scheduler",
  ]
  cloudwatch_log_group_retention_in_days = var.environment == "prod" ? 90 : 14
  enable_irsa                            = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_addons = {
    coredns                = { most_recent = true }
    eks-pod-identity-agent = { most_recent = true }
    kube-proxy             = { most_recent = true }
    vpc-cni                = { most_recent = true }
  }

  enable_cluster_creator_admin_permissions = true
  eks_managed_node_groups                  = merge(local.core_node_groups, local.gpu_node_groups)

  node_security_group_tags = {
    "karpenter.sh/discovery" = local.name
  }
}

resource "aws_kms_key" "artifacts" {
  description             = "ML platform artifact encryption"
  deletion_window_in_days = var.environment == "prod" ? 30 : 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "artifacts" {
  name          = "alias/${local.name}-artifacts"
  target_key_id = aws_kms_key.artifacts.key_id
}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${local.name}-artifacts-"
  force_destroy = var.environment != "prod"
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_policy" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.artifacts.arn,
        "${aws_s3_bucket.artifacts.arn}/*",
      ]
      Condition = {
        Bool = {
          "aws:SecureTransport" = "false"
        }
      }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.artifacts]
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.artifacts.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "artifact-version-retention"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.artifact_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.artifacts]
}

resource "aws_ecr_repository" "images" {
  for_each = toset(["control-plane", "pipeline", "model-server", "mlflow"])

  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.environment != "prod"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.artifacts.arn
  }
}

resource "aws_ecr_lifecycle_policy" "images" {
  for_each   = aws_ecr_repository.images
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after seven days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Retain the newest fifty tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = 50
        }
        action = { type = "expire" }
      }
    ]
  })
}

resource "aws_iam_role" "mlflow_artifact_access" {
  name = "${substr("${local.name}-mlflow-artifacts", 0, 55)}-${substr(sha1(local.name), 0, 8)}"

  assume_role_policy = local.pod_identity_assume_role_policy
}

resource "aws_iam_role_policy" "mlflow_artifact_access" {
  name = "artifact-bucket"
  role = aws_iam_role.mlflow_artifact_access.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation", "s3:ListBucket"]
        Resource = aws_s3_bucket.artifacts.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:DeleteObject",
          "s3:GetObject",
          "s3:ListMultipartUploadParts",
          "s3:PutObject",
        ]
        Resource = "${aws_s3_bucket.artifacts.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
        ]
        Resource = aws_kms_key.artifacts.arn
      },
    ]
  })
}

resource "aws_iam_role" "tenant_pipeline_artifact_access" {
  for_each = var.tenants

  name = "${substr("${local.name}-${each.key}-pipeline", 0, 55)}-${substr(sha1("${local.name}-${each.key}-pipeline"), 0, 8)}"

  assume_role_policy = local.pod_identity_assume_role_policy
}

resource "aws_iam_role_policy" "tenant_pipeline_artifact_access" {
  for_each = var.tenants

  name = "tenant-artifact-read-write"
  role = aws_iam_role.tenant_pipeline_artifact_access[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation"]
        Resource = aws_s3_bucket.artifacts.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.artifacts.arn
        Condition = {
          StringLike = {
            "s3:prefix" = [
              "tenants/${each.key}",
              "tenants/${each.key}/*",
            ]
          }
        }
      },
      {
        Effect = "Allow"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:DeleteObject",
          "s3:GetObject",
          "s3:ListMultipartUploadParts",
          "s3:PutObject",
        ]
        Resource = "${aws_s3_bucket.artifacts.arn}/tenants/${each.key}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
        ]
        Resource = aws_kms_key.artifacts.arn
      },
    ]
  })
}

resource "aws_iam_role" "tenant_serving_artifact_access" {
  for_each = var.tenants

  name = "${substr("${local.name}-${each.key}-serving", 0, 55)}-${substr(sha1("${local.name}-${each.key}-serving"), 0, 8)}"

  assume_role_policy = local.pod_identity_assume_role_policy
}

resource "aws_iam_role_policy" "tenant_serving_artifact_access" {
  for_each = var.tenants

  name = "tenant-artifact-read-only"
  role = aws_iam_role.tenant_serving_artifact_access[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation"]
        Resource = aws_s3_bucket.artifacts.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.artifacts.arn
        Condition = {
          StringLike = {
            "s3:prefix" = [
              "tenants/${each.key}",
              "tenants/${each.key}/*",
            ]
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.artifacts.arn}/tenants/${each.key}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.artifacts.arn
      },
    ]
  })
}

resource "aws_eks_pod_identity_association" "mlflow_artifacts" {
  cluster_name    = module.eks.cluster_name
  namespace       = "ml-platform-system"
  service_account = "mlflow"
  role_arn        = aws_iam_role.mlflow_artifact_access.arn

  depends_on = [module.eks]
}

resource "aws_eks_pod_identity_association" "tenant_pipeline_artifacts" {
  for_each = var.tenants

  cluster_name    = module.eks.cluster_name
  namespace       = each.key
  service_account = "ml-developer"
  role_arn        = aws_iam_role.tenant_pipeline_artifact_access[each.key].arn

  depends_on = [module.eks]
}

resource "aws_eks_pod_identity_association" "tenant_serving_artifacts" {
  for_each = var.tenants

  cluster_name    = module.eks.cluster_name
  namespace       = each.key
  service_account = "model-serving"
  role_arn        = aws_iam_role.tenant_serving_artifact_access[each.key].arn

  depends_on = [module.eks]
}

resource "random_password" "postgres" {
  count = var.enable_managed_metadata_store ? 1 : 0

  length  = 32
  special = false
}

resource "aws_security_group" "postgres" {
  count = var.enable_managed_metadata_store ? 1 : 0

  name_prefix = "${local.name}-postgres-"
  description = "MLflow PostgreSQL access from EKS nodes"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "PostgreSQL from EKS nodes"
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [module.eks.node_security_group_id]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "mlflow" {
  count = var.enable_managed_metadata_store ? 1 : 0

  identifier     = "${local.name}-mlflow"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.postgres_instance_class

  db_name  = "mlflow"
  username = "mlflow"
  password = random_password.postgres[0].result
  port     = 5432

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.artifacts.arn

  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.postgres[0].id]
  publicly_accessible    = false
  multi_az               = var.environment == "prod"

  backup_retention_period = var.environment == "prod" ? 14 : 3
  deletion_protection     = var.environment == "prod"
  skip_final_snapshot     = var.environment != "prod"
  final_snapshot_identifier = (
    var.environment == "prod" ? "${local.name}-mlflow-final" : null
  )

  auto_minor_version_upgrade   = true
  performance_insights_enabled = true
}

resource "aws_secretsmanager_secret" "mlflow_database" {
  count = var.enable_managed_metadata_store ? 1 : 0

  name                    = "${local.name}/mlflow/database"
  recovery_window_in_days = var.environment == "prod" ? 30 : 0
  kms_key_id              = aws_kms_key.artifacts.arn
}

resource "aws_secretsmanager_secret_version" "mlflow_database" {
  count = var.enable_managed_metadata_store ? 1 : 0

  secret_id = aws_secretsmanager_secret.mlflow_database[0].id
  secret_string = jsonencode({
    username = "mlflow"
    password = random_password.postgres[0].result
    host     = aws_db_instance.mlflow[0].address
    port     = 5432
    database = "mlflow"
    uri      = "postgresql+psycopg2://mlflow:${random_password.postgres[0].result}@${aws_db_instance.mlflow[0].address}:5432/mlflow"
  })
}

resource "aws_budgets_budget" "monthly" {
  count = var.budget_notification_email != "" ? 1 : 0

  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$ml-platform-blueprint"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_notification_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_notification_email]
  }
}
