# Architecture decision records

Architecture decision records (ADRs) capture decisions that materially shape
the platform. They are immutable once accepted; a later decision supersedes an
earlier record instead of silently rewriting history.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-platform-product-scope.md) | Treat the repository as a platform product | Accepted |
| [0002](0002-dual-runtime-profile.md) | Keep a runnable reference plane and a Kubernetes profile | Accepted |
| [0003](0003-ml-lifecycle-components.md) | Use KFP, MLflow, and KServe behind explicit contracts | Accepted |
| [0004](0004-policy-driven-promotion.md) | Separate registration, promotion, and traffic | Accepted |
| [0005](0005-multi-tenant-resource-governance.md) | Combine namespace isolation with Kueue admission | Accepted |
| [0006](0006-gitops-and-supply-chain.md) | Reconcile signed, digest-pinned releases with GitOps | Accepted |
| [0007](0007-observability-and-slo.md) | Make lifecycle and tenant signals first-class telemetry | Accepted |
| [0008](0008-local-consumer-gpu-profile.md) | Separate consumer-GPU execution from the cluster GPU plane | Accepted |

## Format

Every record states its context, decision, consequences, and alternatives.
Operational detail belongs in a runbook; a decision that changes a prior ADR
must name the record it supersedes.
