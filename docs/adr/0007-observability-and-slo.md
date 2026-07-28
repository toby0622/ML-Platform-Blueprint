# ADR 0007: Make lifecycle and tenant signals first-class telemetry

- Status: Accepted
- Date: 2026-07-28
- Owners: ML Platform team

## Context

Infrastructure health alone cannot answer whether a model is serving the wrong
version, whether a tenant is starved in a queue, or whether a promotion caused a
quality regression. Unbounded model, tenant, or request labels can also make a
metrics backend unstable.

## Decision

Publish bounded Prometheus metrics for:

- request volume, error rate, and latency by route and deployed version;
- training and promotion outcomes;
- Kueue admission and wait time by queue;
- GPU allocation and DCGM utilization;
- control-plane readiness and dependency failures.

Propagate request/run identifiers through structured logs and OpenTelemetry.
Alert on symptoms tied to an operator action, and document that action in a
runbook. Keep request IDs, user IDs, and raw prompts out of metric labels.

The initial service objective is 99.5% successful prediction availability over
30 days, with p95 latency objectives defined per runtime profile. Error-budget
burn alerts use short and long windows; model quality remains a separate gate.

## Consequences

- A rollout can be correlated with service and model behavior.
- Tenant contention becomes visible instead of anecdotal.
- Dashboards and alerts need periodic review as labels and workloads evolve.
- The local profile demonstrates metric contracts but cannot establish a
  production SLO without representative traffic and infrastructure.

## Alternatives considered

- **Logs only:** rejected because aggregation and multi-window alerting would be
  fragile.
- **Every identifier as a label:** rejected because cardinality would grow
  without bound.
- **One global latency objective:** rejected because CPU prediction and GPU LLM
  token generation have fundamentally different latency semantics.
