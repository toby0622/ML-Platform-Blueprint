# Operations runbooks

These procedures are designed for the Kubernetes profile. Replace example
names only after confirming the affected tenant, model, namespace, and time
window. Preserve command output in the incident record.

| Signal | Runbook |
|---|---|
| Bad candidate behavior or promotion alert | [Model rollout and rollback](model-rollout-and-rollback.md) |
| API unavailable or dependency failures | [Control-plane unavailable](control-plane-unavailable.md) |
| MLflow, PostgreSQL, or object-store errors | [Registry or object-store outage](registry-or-object-store-outage.md) |
| Unschedulable GPU pods or DCGM errors | [GPU capacity unavailable](gpu-capacity-unavailable.md) |
| Long Kueue wait time or tenant starvation | [Queue starvation](queue-starvation.md) |

## Common rules

1. Declare severity, incident commander, start time, and affected tenants.
2. Prefer reversible traffic or admission changes before data-plane changes.
3. Never delete artifacts, runs, persistent volumes, or queue objects as a
   diagnostic shortcut.
4. Do not bypass a quality gate to restore service; select a known-good version.
5. Record every manual action and reconcile emergency changes back into Git.
6. Close only after user impact, metrics, audit history, and follow-up ownership
   are verified.
