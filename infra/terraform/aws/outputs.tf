output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "configure_kubectl_command" {
  description = "Command to configure kubectl."
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}

output "artifact_bucket_name" {
  description = "S3 bucket used for MLflow and model artifacts."
  value       = aws_s3_bucket.artifacts.id
}

output "mlflow_artifact_role_arn" {
  description = "EKS Pod Identity role with platform-level artifact access for MLflow."
  value       = aws_iam_role.mlflow_artifact_access.arn
}

output "tenant_pipeline_artifact_role_arns" {
  description = "Tenant-scoped EKS Pod Identity roles with artifact read/write access."
  value = {
    for tenant, role in aws_iam_role.tenant_pipeline_artifact_access :
    tenant => role.arn
  }
}

output "tenant_serving_artifact_role_arns" {
  description = "Tenant-scoped EKS Pod Identity roles with artifact read-only access."
  value = {
    for tenant, role in aws_iam_role.tenant_serving_artifact_access :
    tenant => role.arn
  }
}

output "ecr_repository_urls" {
  description = "Immutable ECR repositories."
  value       = { for name, repository in aws_ecr_repository.images : name => repository.repository_url }
}

output "mlflow_database_secret_arn" {
  description = "Secrets Manager ARN containing the MLflow PostgreSQL URI."
  value = (
    var.enable_managed_metadata_store
    ? aws_secretsmanager_secret.mlflow_database[0].arn
    : null
  )
}
