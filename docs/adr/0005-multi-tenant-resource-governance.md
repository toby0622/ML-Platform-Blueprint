# ADR 0005: Combine namespace isolation with Kueue admission

- Status: Accepted
- Date: 2026-07-28
- Owners: ML Platform team

## Context

Namespace RBAC prevents many unauthorized API operations but does not prevent
one team from exhausting shared CPU or GPU capacity. ResourceQuota limits a
namespace, yet it cannot express cohort borrowing, admission order, or fair
sharing during contention.

## Decision

Give each tenant:

- a namespace, service account, least-privilege Role/RoleBinding;
- ResourceQuota, LimitRange, default-deny NetworkPolicy, and explicit egress;
- a Kueue LocalQueue backed by a tenant ClusterQueue;
- nominal CPU/GPU quota, bounded borrowing within a Cohort, fair sharing,
  priority classes, and preemption policy.

Tenant identity is carried into API authorization, artifact paths, metrics, and
audit events. Platform controllers operate in dedicated namespaces and receive
only the cross-namespace permissions their controller requires.

## Consequences

- Security isolation and capacity fairness are addressed independently.
- Idle quota can be borrowed without becoming a permanent entitlement.
- Operators must monitor queue age, admission, preemption, and GPU utilization.
- NetworkPolicy effectiveness depends on the cluster network plugin.
- Hard multi-tenant or hostile-code workloads need stronger sandboxing and
  possibly separate clusters.

## Alternatives considered

- **Namespace and RBAC only:** rejected because it does not govern scarce compute.
- **Static per-team node pools:** rejected as the default because it strands idle
  capacity, though dedicated pools remain valid for strong isolation.
- **First-come, first-served queue:** rejected because it permits noisy-neighbor
  starvation.
