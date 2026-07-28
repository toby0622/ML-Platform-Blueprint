variable "aws_region" {
  description = "AWS region for the platform."
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "Environment name."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "ml-platform"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,38}[a-z0-9]$", var.cluster_name))
    error_message = "cluster_name must be a 3-40 character lower-case DNS-style name."
  }
}

variable "kubernetes_version" {
  description = "EKS Kubernetes minor version."
  type        = string
  default     = "1.33"
}

variable "tenants" {
  description = "Tenant namespaces that receive prefix-scoped artifact identities."
  type        = set(string)
  default     = ["team-a", "team-b"]

  validation {
    condition = (
      length(var.tenants) > 0
      && alltrue([
        for tenant in var.tenants :
        can(regex("^[a-z][a-z0-9-]{1,61}[a-z0-9]$", tenant))
      ])
    )
    error_message = "tenants must contain one or more lower-case DNS-style names."
  }
}

variable "vpc_cidr" {
  description = "VPC IPv4 CIDR."
  type        = string
  default     = "10.42.0.0/16"
}

variable "availability_zone_count" {
  description = "Number of availability zones."
  type        = number
  default     = 3

  validation {
    condition     = var.availability_zone_count >= 2 && var.availability_zone_count <= 3
    error_message = "availability_zone_count must be 2 or 3."
  }
}

variable "system_instance_types" {
  description = "Allowed instance types for the system node group."
  type        = list(string)
  default     = ["m7i.large"]
}

variable "cpu_ml_instance_types" {
  description = "Allowed instance types for CPU ML workloads."
  type        = list(string)
  default     = ["m7i.xlarge", "m7a.xlarge"]
}

variable "enable_gpu_nodes" {
  description = "Create an NVIDIA A10G managed node group."
  type        = bool
  default     = false
}

variable "gpu_instance_types" {
  description = "Allowed GPU instance types."
  type        = list(string)
  default     = ["g5.xlarge"]
}

variable "enable_managed_metadata_store" {
  description = "Create RDS PostgreSQL for MLflow metadata."
  type        = bool
  default     = false
}

variable "postgres_instance_class" {
  description = "RDS instance class when the metadata store is enabled."
  type        = string
  default     = "db.t4g.medium"
}

variable "artifact_retention_days" {
  description = "Days before non-current artifact versions expire."
  type        = number
  default     = 90

  validation {
    condition     = var.artifact_retention_days >= 30
    error_message = "artifact_retention_days must be at least 30."
  }
}

variable "monthly_budget_usd" {
  description = "Monthly AWS budget threshold."
  type        = number
  default     = 500

  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be greater than zero."
  }
}

variable "budget_notification_email" {
  description = "Optional email for actual and forecast budget alerts."
  type        = string
  default     = ""
}
