# Acceptance evidence

This matrix distinguishes executable evidence from environment-dependent
evidence. “Static” means source is parsed/rendered in CI. “Runtime” means a test
executes the behavior. Hardware and cloud claims remain pending until their
target environment produces an attached report.

| Acceptance criterion | Implementation | Verification |
|---|---|---|
| Rebuildable | `pyproject.toml`, Dockerfiles, Compose, kind scripts, Helm, Terraform | CI install/build/render; repository validator |
| Reproducible | deterministic generator/split/training; canonical JSON; code/data/parameter capture | `test_dataset_is_reproducible_and_content_addressed`, model round-trip test |
| Traceable | run and version registry, tracking snapshots, MLflow mirror, model cards | lifecycle integration test; audit API e2e |
| Extensible | `ModelArtifact` schema, KFP component entrypoints, KServe V1/V2 runtime | model-server V1/V2 e2e; KFP compile in CI |
| Deployable | offline `QualityGatePolicy`, explicit promotion endpoint | healthy lifecycle and failed-gate integration tests |
| Rollbackable | transactional deployment state, stable/canary aliases, online SLI policy | healthy finalize and bad-canary automatic rollback tests |
| Observable | Prometheus metrics, alert rules, Grafana dashboard, instrumented API, OTel gateway | metrics API e2e and span-export unit test; YAML/JSON validation; Compose/K8s runtime when available |
| Isolated | API tenant allowlist; namespaces, RBAC, quotas, limits, NetworkPolicy, Kyverno; tenant-scoped S3 Pod Identities | tenant test; Kustomize/Terraform validation; cluster policy game day pending |
| Benchmarkable | deterministic request IDs, raw samples, p50/p95/p99, TTFT/ITL/token throughput, RTX scenario orchestration, GPU telemetry, cost calculator | benchmark unit tests; CPU baseline; RTX preflight, CUDA container, health/chat, 900-request vLLM evidence |
| Explainable | architecture, threat model, ADRs, runbooks, postmortem, articles | required-evidence repository validation |

Current local verification: 66 tests pass with 89.37% statement/branch coverage,
strict mypy passes for all 17 package modules, Ruff passes, and the repository
validator parses 54 YAML and 8 JSON evidence/configuration files. The KFP
pipeline compiles, both first-party and official MLflow charts lint/render, all
nine Kustomize targets render, and Terraform format/validate passes. Counts are
expected to evolve; CI is the authoritative check.

## Test-to-risk mapping

| Risk | Test or check |
|---|---|
| Same inputs produce different data/model behavior | deterministic dataset and model round-trip |
| Invalid schema enters training | schema validation unit tests |
| Weak model receives traffic | failed offline gate integration test |
| Canary regression remains live | automatic rollback integration test |
| Retry moves between revisions | deterministic hash routing in lifecycle test |
| Artifact is modified after registration | tamper-detection integration test |
| Tenant outside allowlist creates a run | tenant enforcement test |
| API path/header tenants disagree | API e2e authorization test |
| KServe contract diverges | V1 and V2 model-server e2e tests |
| Invalid YAML/JSON or broken Kustomize reference | repository artifact test |
| Cost math hides utilization | dimensional cost-calculator test |

## Environment-gated verification

The following commands are designed but cannot be truthfully marked complete
without the named environment:

- Docker Compose health and MLflow/PostgreSQL/MinIO integration;
- kind admission, queue fairness, Argo drift self-heal, and KServe rollout;
- authenticated AWS plan/apply and cloud runtime validation (local Terraform
  provider initialization and validation pass);
- GPU Operator/DCGM installation;
- vLLM quantization quality, Kubernetes serving, and cost benchmark.

The local GPU preflight is ready and verifies an RTX 4080 SUPER, 16,376 MiB
VRAM, compute capability 8.9, driver 610.74, WSL 2, Docker Desktop's Linux
engine, and the NVIDIA runtime. A CUDA 13 container, digest-pinned vLLM 0.23.0,
health/models/chat checks, and all three three-run scenarios completed. The
[reviewed GPU evidence](benchmarks/evidence/local-rtx4080-super-vllm-summary.json)
contains 900 successful measured requests, sanitized telemetry, three-run
distributions, and raw/source hashes.

Raw results remain under ignored `benchmark-results/`; reviewed compact evidence
belongs under `docs/benchmarks/evidence/`, with hardware, image digest, model
revision, configuration, warm-up, run count, variance, raw hash, and price
timestamp.
