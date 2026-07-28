# Predictive KServe deployment

`base/` deploys the stable model. `overlays/canary/` changes the immutable
artifact URI and routes 10% of traffic to the new KServe revision.

The model-serving ServiceAccount needs workload identity for its tenant-scoped
object-store prefix; the AWS profile creates a read-only EKS Pod Identity
association. No credential is committed to this repository. The KServe 0.17
`storageUris` contract injects a storage initializer that places `model.json`
under `/mnt/models` before readiness succeeds. Replace the bucket placeholder
with the Terraform `artifact_bucket_name` output. Both stable and candidate
URIs remain within `tenants/team-a/`, matching the serving identity's
read-only IAM prefix.

Promotion sequence:

```bash
kubectl apply -k serving/kserve/predictive/base
kubectl apply -k serving/kserve/predictive/overlays/canary
# Observe SLIs, then either promote the candidate or re-apply base to roll back.
```
