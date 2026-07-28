# ADR 0002: Keep a runnable reference plane and a Kubernetes profile

- Status: Accepted
- Date: 2026-07-28
- Owners: ML Platform team

## Context

The production target uses Kubernetes, MLflow, KFP, KServe, Kueue, and optional
GPUs. Requiring that entire stack for every code change would make the feedback
loop slow, expensive, and inaccessible on a laptop. A mock-only sample, however,
would hide the concurrency, artifact, and promotion behaviors the project is
meant to demonstrate.

## Decision

Maintain two connected runtime profiles:

- a deterministic Python reference plane using NumPy and SQLite for lifecycle,
  policy, routing, audit, API, CLI, and tests;
- a Kubernetes profile mapping the same stages and contracts to KFP, MLflow,
  KServe, Kueue, policy controls, and production storage.

The profiles share artifact metadata, metric names, promotion semantics, tenant
identity, and serving payloads. SQLite is explicitly a single-replica local
implementation, not a production high-availability database.

## Consequences

- Contributors can run meaningful end-to-end tests without cloud credentials.
- Kubernetes manifests remain tied to executable behavior.
- Some integration failures can only be discovered in a target cluster, so CI
  renders manifests while environment-specific validation remains required.
- A PostgreSQL control-plane registry adapter is required before horizontally
  scaling the custom API.

## Alternatives considered

- **Kubernetes only:** rejected because it creates a high-friction development
  loop and makes review difficult.
- **Local implementation only:** rejected because it would not demonstrate
  multi-tenant scheduling, policy, GPU operation, or GitOps.
