# ADR 0001: Treat the repository as a platform product

- Status: Accepted
- Date: 2026-07-28
- Owners: ML Platform team

## Context

A collection of model-training notebooks does not demonstrate the responsibilities
of an AI Platform Engineer. The intended users are data scientists, ML engineers,
application teams, and platform operators. Each group needs a stable interface,
guardrails, and operational evidence rather than access to implementation details.

The project also needs an honest boundary: it can prove platform behavior with a
small deterministic model, but it cannot prove that a synthetic churn model has
business value.

## Decision

Build an internal platform product around a complete model lifecycle:

1. validate data and train deterministically;
2. evaluate and register an immutable artifact with lineage;
3. apply an explicit offline promotion policy;
4. route a measurable canary and either finalize or roll back;
5. expose the workflow through an API, CLI, pipeline, and GitOps resources;
6. publish telemetry, audit records, runbooks, and acceptance evidence.

The classifier remains intentionally simple. Engineering quality attributes—
reproducibility, traceability, isolation, deployability, rollback, and
observability—are the primary deliverable.

## Consequences

- Platform contracts can be exercised without judging model novelty.
- Documentation and operations are part of the product, not follow-up work.
- Scope excludes a feature store, notebook service, labeling system, and
  general-purpose AutoML.
- A future model family can reuse the lifecycle if it implements the documented
  artifact and serving contracts.

## Alternatives considered

- **Kaggle-style model optimization:** rejected because it tests modeling skill
  but not platform engineering.
- **Infrastructure-only repository:** rejected because unexercised YAML does not
  prove that lifecycle contracts work.
