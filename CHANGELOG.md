# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
semantic versioning.

## [Unreleased]

### Added

- Deterministic synthetic-data training and evaluation lifecycle.
- Immutable JSON model artifacts, checksums, model cards, lineage, and audit.
- Offline quality gates, stable/canary routing, online gates, and rollback.
- FastAPI control API, CLI, Prometheus metrics, and KServe V1/V2 model runtime.
- Typed KFP pipeline and optional MLflow mirror.
- Docker Compose profile with PostgreSQL, MinIO, MLflow, Prometheus, and Grafana.
- Helm, Argo CD, KServe, Kueue, tenant, Kyverno, GPU Operator, and OTel profiles.
- AWS VPC/EKS/ECR/S3/KMS, tenant-scoped EKS Pod Identity, and optional RDS/GPU
  Terraform blueprint.
- Signed production MLflow image with PostgreSQL/S3 clients, SBOM, and
  provenance.
- API tracing through a resilient OpenTelemetry Collector gateway into MLflow.
- Load, LLM inference, capacity, and cost benchmark tooling.
- RTX 4080 SUPER local vLLM profile with WSL/Docker preflight, pinned model and
  runtime, scenario orchestration, GPU telemetry, evidence manifest, and a
  single-replica KServe Ada overlay.
- Runtime-validated CUDA passthrough, loopback-only vLLM health/chat, and three
  measured RTX scenarios covering 900 successful requests with reviewed
  secret-free evidence.
- Unit, integration, API, model-server, and repository validation tests.
- ADRs, runbooks, threat model, demo, acceptance matrix, articles, roadmap, and
  synthetic postmortem.

## [0.1.0] - 2026-07-28

### Added

- First complete portfolio release of ML Platform Blueprint.

[Unreleased]: https://github.com/toby0622/ML-Platform-Blueprint/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/toby0622/ML-Platform-Blueprint/releases/tag/v0.1.0
