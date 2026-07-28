# Target role and skill-gap matrix

## Positioning

> A platform and infrastructure engineer extending production Kubernetes,
> automation, and developer-platform expertise into ML lifecycle, GPU
> orchestration, and model-serving systems.

Primary target: **AI Platform Engineer / MLOps Platform Engineer**.

Secondary direction, now supported by local GPU evidence:
**Inference Platform Engineer**.

## Role outcomes demonstrated here

- build a self-service golden path rather than one-off notebooks;
- make training and model delivery reproducible and auditable;
- control promotion, canary, rollback, and failure recovery;
- isolate tenants and allocate scarce compute fairly;
- expose service, model, pipeline, queue, and GPU signals;
- explain control-plane/data-plane, reliability, security, capacity, and cost
  trade-offs.

## Skill matrix

| Capability | Repository evidence | Remaining production evidence |
|---|---|---|
| Python service/package quality | typed package, FastAPI, CLI, tests, container | production traffic and ownership |
| Kubernetes platform | Helm, Kustomize, RBAC, quota, policy, KServe | CKA and real cluster game days |
| CI/CD and supply chain | test/build/scan/SBOM/provenance/sign | protected release environment |
| ML lifecycle | deterministic pipeline, metrics, registry, model card | real dataset/domain review |
| GitOps | Argo CD applications, self-heal/prune | drift demonstration on cluster |
| Scheduling | Kueue cohorts, quota, priority, fair sharing | measured queue behavior |
| Observability | metrics, alerts, dashboard, traces | SLO calibration from usage |
| GPU operations | Operator/DCGM values, scheduler flavor, Docker/WSL CUDA passthrough, RTX telemetry | native cluster and rented GPU validation |
| LLM serving | KServe/vLLM manifest, health/chat, 900-request TTFT/ITL/throughput evidence | KServe runtime, representative prefixes, quality/cost |
| Cloud/IaC | EKS, S3/KMS, ECR, tenant-scoped Pod Identity, optional RDS/budget | reviewed plan/apply/destroy |

## Resume-ready statement

Designed and implemented a Kubernetes-oriented self-service ML platform
blueprint that automates deterministic training, evaluation, lineage,
policy-gated promotion, canary delivery, and rollback, with tenant quotas,
queue fairness, software-supply-chain controls, and end-to-end telemetry.

The local GPU result can support a scoped quantitative bullet: three scenarios,
900 successful requests, and immutable/hashed evidence on one RTX 4080 SUPER.
Production-scale, cost, availability, and Kubernetes claims still require
cluster and game-day evidence.
