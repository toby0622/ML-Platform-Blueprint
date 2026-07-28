# Threat model

## Assets

- model artifacts and their lineage;
- training data references and evaluation results;
- tenant credentials and service identities;
- production routing state;
- GPU capacity and cluster availability;
- CI provenance and image signatures.

## Threat actors and assumptions

The design considers a compromised tenant workload, an over-privileged user,
an accidental operator change, a malicious or vulnerable image, leaked object
store credentials, and tampered artifacts. Cluster administrators and the cloud
control plane remain trusted; protecting against a fully compromised cluster
administrator requires a separate trust domain.

## Main threats and controls

| Threat | Preventive control | Detective/recovery control |
|---|---|---|
| Cross-tenant API access | tenant path/header check; namespace RBAC | audit events and API logs |
| Cross-tenant network access | default-deny ingress/egress, explicit namespace flows, exact Pod Identity agent address; public HTTPS only for artifact/model downloads | flow logs, DNS-aware egress policy, and policy tests |
| Resource starvation | ResourceQuota, LimitRange, Kueue quota/borrowing | queue wait and quota dashboards |
| Privileged workload | restricted Pod Security and Kyverno | policy reports |
| Mutable or untrusted image | digest policy, keyless Cosign verification | CI provenance and registry scan |
| Mutable remote LLM model | default Hugging Face revision pin; secret-free run manifest records model revision and image digest | artifact/config SHA-256 and reviewed benchmark evidence |
| Artifact replacement | immutable version path and SHA-256 verification | integrity failure and audit |
| Bad model promotion | explicit offline and online gates | automatic canary rollback |
| Credential exposure in Git | repository validation rejects Secret payloads | secret scanning in hosting platform |
| Metadata loss | PostgreSQL backup/PITR design | restore runbook and game day |
| Cross-tenant artifact access | per-tenant Pod Identity and S3 prefix policy; serving is read-only | CloudTrail and access-denied metrics |
| Object-store deletion | versioning, KMS, prefix-scoped write identity | retention and restore procedure |
| Denial of service | request limits, Kueue admission, autoscaling | SLO alerts and load shedding backlog |

## Residual risks

- NetworkPolicy behavior depends on the selected CNI.
- MLflow workspaces are a logical authorization boundary, not a hard
  compliance boundary. Direct tenant pipeline and serving identities are
  prefix-scoped, but the shared MLflow service has platform-level artifact
  access; regulated tenants may need separate deployments and buckets.
- The lab image policy uses repository-scoped GitHub OIDC identity. Production
  should also constrain reusable workflows, environments, and protected tags.
- The reference API has no end-user identity provider. Place it behind an
  authenticated gateway and derive tenant identity from verified claims.
- Model confidentiality at runtime is not solved by disk encryption. Consider
  dedicated nodes, confidential compute, and stricter egress for sensitive
  weights.

## Security verification

1. attempt a cross-namespace resource read with each tenant identity;
2. submit a pod without resources and a privileged pod;
3. submit a mutable and then an unsigned image under the production overlay;
4. alter `model.json` after registration and verify inference fails closed;
5. rotate object-store and database credentials without rebuilding images;
6. confirm audit records contain no secrets or raw training rows.
7. inspect a local vLLM benchmark manifest and confirm `HF_TOKEN` is absent.
