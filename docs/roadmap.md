# Roadmap

The repository separates completed, locally proven behavior from work that needs
a target environment.

## Stage A: CPU end-to-end MLOps — implemented

- deterministic data validation, training, evaluation, registry, and lineage;
- quality gate, stable/canary routing, automatic/manual rollback, and audit;
- CLI, REST API, KServe-compatible model runtime, metrics, and tests;
- KFP pipeline, MLflow profile, Helm chart, Compose, CI, and GitOps resources.

## Stage B: LLM inference and benchmarking — local runtime measured

- KServe Hugging Face/vLLM serving manifest;
- versioned prompt and concurrency scenarios;
- TTFT, ITL, end-to-end, token-throughput benchmark client;
- Docker Desktop/WSL 2 CUDA passthrough and a 900-request RTX 4080 SUPER report;
- capacity and cost model with explicit assumptions;
- GPU Operator, DCGM, dashboard, and alerting profile.

Local single-GPU evidence is complete. Native-Linux, Kubernetes, cloud-GPU,
quantization-quality, and cost evidence remains environment-dependent.

## Stage C: multi-tenant reliability — blueprint implemented

- tenant namespace, identity, RBAC, quota, LimitRange, and network boundaries;
- Kueue cohort, fair sharing, borrowing, priority, and preemption;
- Kyverno baseline and production signature verification overlay;
- incident runbooks, threat model, synthetic postmortem, and AWS topology.

## Next production increments

1. Replace the custom control registry with PostgreSQL and validate concurrent
   replicas, failover, backup, and point-in-time recovery.
2. Add OIDC authorization with tenant claims at the API gateway and remove the
   demonstration header trust boundary.
3. Add External Secrets reconciliation from Secrets Manager and test database
   credential rotation without downtime.
4. Exercise kind in CI and the production profile in an ephemeral EKS test
   account.
5. Run load, chaos, and recovery tests in-cluster; repeat the vLLM profile on
   native Linux and a named cloud GPU with representative unique prefixes.
6. Add fairness, drift, privacy, and human-approval policies for a real domain.
7. Automate release evidence attachment as a prerequisite to canary promotion.
