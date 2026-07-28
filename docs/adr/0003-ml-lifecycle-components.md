# ADR 0003: Use KFP, MLflow, and KServe behind explicit contracts

- Status: Accepted
- Date: 2026-07-28
- Owners: ML Platform team

## Context

Pipeline orchestration, experiment lineage, and online serving have different
failure modes and scaling characteristics. Building all three as one service
would couple scheduling, metadata, and request serving. Choosing tools without
contracts would merely move that coupling into vendor-specific formats.

## Decision

Use:

- Kubeflow Pipelines (KFP) for typed, cacheable validate/train/evaluate/register
  orchestration;
- MLflow with PostgreSQL and object storage for shared run and model metadata;
- KServe for predictive and Hugging Face/vLLM serving.

Components exchange versioned files and JSON metadata, never in-process Python
objects. The canonical model artifact is non-executable JSON with a SHA-256
checksum. The reference registry stores the same lineage fields locally.

## Consequences

- Stages can be retried and inspected independently.
- The serving plane does not need pipeline credentials.
- Tool upgrades require contract and manifest compatibility tests.
- Portable JSON favors safety and reviewability over support for every model
  framework; additional formats must define a loader and security policy.

## Alternatives considered

- **One custom monolith:** rejected because orchestration, tracking, and serving
  would scale and fail together.
- **Pickle artifacts:** rejected because deserialization can execute code and
  weakens supply-chain guarantees.
- **Direct pipeline-to-serving deployment:** rejected because it bypasses an
  auditable promotion decision.
