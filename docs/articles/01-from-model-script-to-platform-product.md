# From model script to platform product

Training a model is not the hard part of operating one. The hard part is making
every change reproducible, attributable, safe to expose, cheap to undo, and
visible while several teams share the same infrastructure.

This article explains the design behind ML Platform Blueprint. The model is a
small NumPy logistic regression on deterministic synthetic data. That choice is
intentional: it keeps attention on the engineering system around the model.

## Start with a release contract

A pipeline that ends with “training succeeded” has only proved that a process
exited with code zero. It has not proved that the data had the expected shape,
the artifact is the one that was evaluated, the candidate is better than the
stable version, or the service can handle representative traffic.

The blueprint makes those states explicit:

```text
validate -> train -> evaluate -> register
         -> offline gate -> canary -> online gate -> promote | rollback
```

Each stage emits a file or metadata document with a checksum. Registration
creates an immutable version; it does not move production traffic. Promotion
records observed metrics, thresholds, actor, reason, and outcome. This makes a
release explainable without reconstructing it from transient logs.

## Reproducibility needs more than a random seed

A seed is useful, but it is only one input. A reproducible run also records:

- the data schema and content hash;
- train/evaluation split parameters;
- model hyperparameters and decision threshold;
- code revision and component image;
- metrics and evaluation sample count;
- artifact checksum and parent run identifier.

The local reference plane writes these values next to a portable JSON artifact
and model card. The Kubernetes profile carries the same contract through typed
KFP components and MLflow. If a result cannot be connected to its inputs and
code, it is an anecdote rather than evidence.

## Separate quality from traffic

The first gate evaluates predictive behavior: accuracy, F1, ROC-AUC, calibration
through Brier score, and sample size. A later gate evaluates service behavior:
candidate error-rate delta and p95 latency relative to stable.

This separation prevents two common category errors. A fast model can still be
wrong, and an accurate model can still exhaust memory or violate a caller
timeout. Neither gate proves fairness or business value; those are additional
policies owned by the domain.

Canary assignment hashes tenant plus request identity. A retry therefore reaches
the same version, which helps debugging and avoids exposing one logical request
to inconsistent behavior. If the online gate fails, the candidate route is
removed atomically while the artifact and evidence remain available.

## Build a real laptop loop

Production manifests are important, but asking every contributor to boot a full
ML stack makes basic behavior expensive to test. The repository therefore has a
dual profile:

- a Python/SQLite reference plane for fast lifecycle, concurrency, API, and
  policy tests;
- a Kubernetes mapping using KFP, MLflow, KServe, Kueue, policy, and cloud
  primitives.

The reference plane is not presented as highly available. Its value is that the
same lifecycle can be inspected in seconds and exercised in CI. Production
storage and controllers then replace implementations without changing the
meaning of registration or promotion.

## Treat operations as source code

Dashboards alone are not operational readiness. Useful telemetry starts with a
question and ends with an action:

- Which version and route are producing errors?
- Is a tenant waiting because of quota, physical capacity, or a flavor mismatch?
- Did a promotion consume the error budget?
- Can a serving pod reload its immutable artifact?

Alerts in the blueprint link to runbooks for rollout, control-plane, storage,
GPU, and queue incidents. A synthetic postmortem tests whether telemetry,
automatic rollback, audit, and human response form a complete loop. This
evidence is as important as a green unit test.

## What production-ready really means

“Production-grade” should describe demonstrated properties, not the mere
presence of Kubernetes YAML. The blueprint uses a narrower claim:

- local lifecycle behavior is executable and tested;
- manifests are rendered and statically validated in CI;
- target-cluster, GPU, scale, recovery, and security claims require environment
  evidence;
- known limitations remain visible.

That honesty is a platform feature. It tells a future operator what has been
proved, what is an architectural path, and which assumptions need validation
before real users depend on the system.
