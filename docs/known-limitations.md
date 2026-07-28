# Known limitations and future design

## Current limitations

1. **The custom reference registry is single-replica.** SQLite plus a
   ReadWriteOnce volume makes local behavior easy to inspect but is not a
   horizontally scalable control-plane store.
2. **API authentication is intentionally delegated.** The API verifies tenant
   consistency but does not implement OIDC. A production gateway must derive
   tenant and actor from authenticated claims rather than trusting headers.
3. **Synthetic data proves mechanics only.** It does not establish business
   value, fairness, privacy, robustness, or production drift behavior.
4. **KFP registration and the local registry are two adapters.** Both preserve
   the same lineage contract, but a production control plane should use MLflow
   as the authoritative registry through one repository interface.
5. **Canary SLIs are submitted to the reference API.** Production should query
   a metrics backend through a rollout controller and bind the observation
   window to the exact KServe revisions.
6. **No feature store.** This avoids hiding the primary lifecycle behind another
   large dependency. Online/offline feature consistency needs a separate ADR
   when a real workload requires it.
7. **Local GPU inference is measured, but only in a narrow environment.**
   The reviewed run covers one RTX 4080 SUPER, Docker Desktop/WSL 2, a local
   client, one unquantized 1.5B model, and a desktop-shared physical GPU. It
   does not validate native Linux, Kubernetes/KServe, autoscaling, multi-GPU,
   DCGM, quantized-output quality, or cost. WSL NVML may leave some telemetry
   fields unavailable.
8. **NetworkPolicy is CNI-dependent.** The portable profile permits public
   HTTPS for object/model downloads and the exact EKS Pod Identity agent
   address. DNS, gateway, object-store, and monitoring flows must be verified
   against the target CNI and service mesh. Production should replace broad
   HTTPS egress with VPC endpoints and a CNI-specific FQDN or L7 policy.
9. **Disaster recovery is designed, not certified.** RTO/RPO remain objectives
   until backup and restore game days measure them.
10. **Dependency upgrades are not automatic promotions.** Dependabot opens
    changes, but KServe/KFP/Kueue/GPU compatibility needs a staging matrix.
11. **MLflow tenancy is logical in the lab profile.** Tenant tags and model
    names make ownership visible. The AWS tenant pipeline/serving identities
    are S3-prefix-scoped, but the shared MLflow service still has platform-level
    artifact access and is not a hard compliance boundary. Regulated tenants
    need separate deployments, databases, and buckets.
12. **Artifact publication is environment-specific.** The KFP registration
    component logs an artifact to MLflow, while KServe requires an object-store
    URI it can read. A production adapter must publish that immutable artifact,
    verify its digest, and write the resulting tenant-scoped URI into the
    deployment reconciliation record.
13. **Promotion is API-driven, not continuously reconciled.** The reference
    control plane proves gates, deterministic routing, and rollback semantics;
    a production controller must reconcile desired MLflow aliases and observed
    KServe revision state.

## Prioritized roadmap

### P0 — harden the control plane

- implement `RegistryRepository` with PostgreSQL and object-storage adapters;
- add OIDC authentication, claim-to-tenant mapping, and authorization tests;
- use optimistic concurrency/version fields for promotion commands;
- replace the local latency summary with explicit HTTP histogram buckets and
  calibrate bounded-cardinality attributes from production traffic;
- add OpenAPI client generation and idempotency keys.

### P1 — automated Kubernetes delivery

- add a promotion controller that reconciles MLflow aliases to KServe;
- query Prometheus for revision-specific canary windows;
- add Argo Rollouts or KServe-native automated steps;
- install External Secrets and rehearse database credential rotation;
- execute conformance and chaos tests in ephemeral CI clusters.

### P2 — model and data governance

- signed model manifests and SBOM-like artifact inventory;
- data-contract registry and drift/equality checks;
- subgroup evaluation and approval ownership;
- retention, legal hold, deletion, and provenance APIs.

### P3 — inference efficiency

- repeat a representative unique-prefix profile on native Linux and a rented
  A10G/L4 for cross-hardware analysis;
- compare quantization with three runs and a separate output-quality gate;
- extend the measured TTFT, ITL, throughput, memory, and power evidence with
  KV-cache metrics and native-Linux/DCGM telemetry;
- model queue-aware autoscaling and cost per million tokens;
- evaluate KServe `LLMInferenceService` for prefix-aware routing and
  disaggregated prefill/decode.

## Definition of future “production ready”

The phrase should be used only after:

- multiple replicas pass failure and concurrency tests;
- authentication and authorization are externally reviewed;
- restore drills meet measured RTO/RPO;
- SLOs have traffic-based burn alerts;
- capacity and cost are based on representative load;
- upgrades and rollback are rehearsed in staging;
- an owning team accepts pager, security, and lifecycle responsibilities.
