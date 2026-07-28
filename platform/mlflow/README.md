# MLflow deployment profiles

MLflow's official 3.14 chart is consumed directly from the immutable commit
behind its release tag rather than copied here.

- `values-lab.yaml` is a single-replica, PVC-backed kind profile.
- `values-production.yaml` expects PostgreSQL, S3, workload identity, and a
  Secret named `mlflow-db-secret`. Replace the artifact bucket and hostname
  before use. Terraform creates the `mlflow` EKS Pod Identity association.
  This profile uses the release-built `ml-platform-blueprint-mlflow` image,
  which layers the PostgreSQL and S3 clients on the pinned upstream MLflow
  image. The same release workflow signs this image and publishes its SBOM and
  provenance.

SQLite is deliberately restricted to the lab. Production uses the Terraform
outputs under `infra/terraform/aws` and enables MLflow workspaces for logical
team separation. Kubernetes namespaces and object-store IAM remain the hard
isolation boundary.
