# AWS production profile

This Terraform root creates:

- a multi-AZ VPC and EKS cluster;
- separate system, Spot CPU-ML, and optional A10G node groups;
- a KMS-encrypted, versioned artifact bucket;
- immutable, scan-on-push ECR repositories;
- workload-identity access for MLflow, training, and model serving;
- optional RDS PostgreSQL plus a Secrets Manager connection record;
- monthly forecast and actual-cost alarms.

Nothing is applied automatically. These resources incur real AWS cost.

```bash
cp terraform.tfvars.example terraform.tfvars
cp backend.hcl.example backend.hcl
# Replace all placeholders and review costs first.
terraform init -backend-config=backend.hcl
terraform fmt -check
terraform validate
terraform plan -out=ml-platform.tfplan
terraform apply ml-platform.tfplan
```

GPU and RDS are disabled by default. Production should enable RDS, use the
artifact bucket in `platform/mlflow/values-production.yaml`, and install
External Secrets to materialize `mlflow-db-secret`. Terraform creates EKS Pod
Identity associations automatically: MLflow has platform artifact access,
tenant pipeline identities are read/write within `tenants/<tenant>/`, and
tenant serving identities are read-only within that prefix.

Provider selections are committed in `.terraform.lock.hcl`. The AWS provider is
held below v6 because EKS module v20 still uses launch-template blocks removed
from v6. Upgrade the EKS module and provider together, then run `init -upgrade`,
`validate`, and a reviewed plan rather than widening the constraint alone.

The generated PostgreSQL password is present in Terraform state. Keep the
remote state bucket encrypted, versioned, access-logged, and restricted to the
deployment role; never publish a plan or state file as CI evidence.

## Destruction

Before `terraform destroy`, archive MLflow metadata and artifacts, verify the
retention requirement, and remove Kubernetes load balancers. Production enables
RDS deletion protection, and `force_destroy=false` makes a non-empty S3 bucket
block destruction. An empty bucket can still be deleted, so preservation
depends on the reviewed backup and retention procedure.
