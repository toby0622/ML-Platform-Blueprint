# 8–12 minute English demo script

## 0:00–1:00 — problem and scope

“This project is an ML platform, not a model leaderboard project. The user is a
data scientist who needs a reproducible path from parameters and data to a
registered, safely deployed, observable model. The operator needs tenant
isolation, capacity control, audit, rollback, and cost evidence.”

Show the architecture in the README. Point out the laptop reference plane and
the Kubernetes production blueprint.

## 1:00–2:30 — repository and quality

Show:

```bash
pytest -q
python scripts/validate_repository.py
```

Explain that tests cover deterministic data, schema failure, offline gate
rejection, canary routing, automatic rollback, artifact tampering, tenant
access, and KServe V1/V2 protocols.

## 2:30–4:30 — reproducible training and lineage

Run:

```bash
ml-platform --state-dir .demo --tenant team-a --model churn train
ml-platform --state-dir .demo status
```

Open `.demo/artifacts/team-a/churn/1/metadata.json` and `MODEL_CARD.md`.
Connect code revision, dataset checksum, parameters, metrics, run ID, model
version, and artifact checksum.

## 4:30–6:30 — promotion and safe rollout

Run:

```bash
ml-platform --state-dir .demo --tenant team-a --model churn promote \
  --version 1 --actor demo --reason "baseline passed review"
```

Train version 2 and start a 20% canary. Explain deterministic request-ID
hashing, stable/challenger aliases, and transactional deployment/audit state.
Show both the healthy finalize path and the bad-canary automatic rollback test.

## 6:30–8:00 — Kubernetes platform controls

Show:

- `platform/tenants`: RBAC, quotas, limits, default-deny network policy;
- `platform/kueue`: team queues, cohort borrowing, fair sharing, priorities;
- `platform/policies`: non-root/resource admission and production signature
  verification;
- `serving/kserve`: stable and canary artifact URIs;
- `platform/argocd`: automated prune and self-heal.

Explain why ResourceQuota is the hard ceiling and Kueue is admission/fairness.

## 8:00–9:30 — observability and reliability

Show the Grafana dashboard and Prometheus alerts. Explain the four layers:
service, model, pipeline/queue, and GPU. Open a runbook and synthetic
postmortem. Highlight that a rollback is defined by signals and commands, not
by intuition.

## 9:30–10:30 — GPU, inference, and cost

Show the reviewed RTX evidence and its raw/source hashes. Explain TTFT, ITL,
throughput, GPU memory, prefix caching, concurrency, and why the hot
exact-prompt result cannot be generalized. State explicitly: “All 900 local
measurements succeeded, but this is one WSL 2 workstation and one 1.5B model;
Kubernetes, cloud-GPU, quality, and cost claims still require separate
evidence.”

## 10:30–11:30 — trade-offs and next step

Open `docs/known-limitations.md`. Explain the SQLite single-replica boundary,
external identity requirement, MLflow/PostgreSQL production path, and the next
highest-leverage task: run a cluster game day, then a budget-capped GPU
cross-hardware benchmark with representative unique prefixes.

End with:

“The outcome is an evidence package for AI Platform Engineering: executable
lifecycle code, platform manifests, tests, operational documents, and honest
boundaries.”
