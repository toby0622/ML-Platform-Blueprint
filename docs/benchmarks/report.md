# Benchmark report

## Executive summary

The CPU reference plane completed 1,000 local prediction requests with 100%
availability at concurrency 32. Observed throughput was 749.53 requests/second,
with p50 39.05 ms, p95 55.27 ms, and p99 82.56 ms client-observed latency.

This is a development baseline, not a production capacity claim. It measures one
Uvicorn process, a NumPy model, and a local SQLite registry on one Windows
workstation. It does not measure Kubernetes networking, KServe autoscaling,
remote storage, TLS, multi-replica behavior, or GPUs.

The local RTX 4080 SUPER profile also completed three vLLM scenarios with three
runs at concurrency 1, 2, 4, 8, and 16. All 900 measured requests succeeded.
At concurrency 16, the baseline produced 1,861.45 output tokens/s with p95 TTFT
61.20 ms; constraining the batch-token budget from 4,096 to 128 reduced output
throughput to 1,640.26 tokens/s and raised p95 TTFT to 122.30 ms. These are
local WSL 2 measurements, not production capacity claims.

The machine-readable summary is
[local-cpu-load-summary.json](evidence/local-cpu-load-summary.json); the
secret-free GPU evidence is
[local-rtx4080-super-vllm-summary.json](evidence/local-rtx4080-super-vllm-summary.json).

## Test subject

| Dimension | Value |
|---|---|
| Date | 2026-07-28 |
| Host OS | Windows 11 build 26200, AMD64 |
| CPU | AMD Ryzen 9 9950X, 16 cores / 32 logical processors |
| Python | 3.13.11 |
| Server | One Uvicorn worker, reference FastAPI control/serving plane |
| Model | Deterministic NumPy logistic regression, version 1 |
| Storage | Local SQLite in WAL mode and local immutable JSON artifact |
| Requests | 1,000 |
| Concurrency | 32 client threads |
| Input | One six-feature record per request |
| Timeout | 10 seconds |
| Warm-up | No separate warm-up phase |

The code was an uncommitted working tree based on revision `3666abdd2fd0`.
Because a commit did not yet identify the complete tree, the evidence records
SHA-256 hashes for the benchmark and critical serving files.

## Result

| Metric | Observed |
|---|---:|
| Successful requests | 1,000 / 1,000 |
| Availability | 100% |
| Error rate | 0% |
| Elapsed time | 1.3342 s |
| Throughput | 749.53 requests/s |
| Mean latency | 39.91 ms |
| p50 latency | 39.05 ms |
| p95 latency | 55.27 ms |
| p99 latency | 82.56 ms |
| Maximum latency | 124.50 ms |

All responses were HTTP 200, used the `stable` route, and named model version 1.
The raw 1,000-sample local output had SHA-256
`c0801429d608d50dc4e500c391bdbb81d825c11375f8dd4c8a339afa95630dbb`
and remains in the ignored `benchmark-results/final-local-cpu-load-otel.json`
workspace file. Every request carried a stable `X-Request-Id`; the compact
reviewed evidence records the benchmark and complete serving/tracing source
hashes.

## Reproduction

```bash
ml-platform --state-dir benchmark-results/final-state-otel-20260728 \
  --tenant team-a --model churn-classifier train

ml-platform --state-dir benchmark-results/final-state-otel-20260728 \
  --tenant team-a --model churn-classifier promote \
  --version 1 --actor benchmark \
  --reason "local CPU benchmark after OpenTelemetry integration"

ml-platform --state-dir benchmark-results/final-state-otel-20260728 \
  --tenant team-a --model churn-classifier serve \
  --host 127.0.0.1 --port 18080 --no-access-log

python benchmarks/load/run.py \
  --base-url http://127.0.0.1:18080 \
  --tenant team-a --model churn-classifier \
  --requests 1000 --concurrency 32 --timeout 10 \
  --max-error-rate 0 \
  --output benchmark-results/final-local-cpu-load-otel.json
```

Run at least three repetitions with a warm-up and background-noise controls
before using the numbers to compare revisions. For production sizing, test the
deployed KServe profile at increasing concurrency until either its latency
objective or error budget is violated.

## Local RTX 4080 SUPER vLLM benchmark

The measured runtime was Docker Desktop 4.84.0, Engine 29.6.2, Compose 5.3.1,
and the WSL 2 Linux engine with NVIDIA runtime. A CUDA 13.0.2 container and the
digest-pinned vLLM 0.23.0 image both saw the RTX 4080 SUPER. The model was
`Qwen/Qwen2.5-1.5B-Instruct` at revision
`989aa7980e4cf806f80c7fef2b1adb7bc71aa306`; the API was bound only to
`127.0.0.1:8000`.

Each scenario used five warm-up requests per run, three runs, 20 measured
requests at each concurrency level, and a 128-token output cap:

| Scenario | Prefix cache | Batch-token limit | c=1 output tok/s | c=1 p95 TTFT | c=16 output tok/s | c=16 p95 TTFT | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | off | 4,096 | 171.96 | 16.38 ms | 1,861.45 | 61.20 ms | 0 / 300 |
| Prefix cache | on | 4,096 | 170.66 | 17.78 ms | 1,837.14 | 33.23 ms | 0 / 300 |
| Constrained batch | off | 128 | 168.65 | 18.68 ms | 1,640.26 | 122.30 ms | 0 / 300 |

The repeated five-prompt workload makes the prefix-cache scenario a hot
exact-prompt upper bound. Its lower c=16 TTFT was observed, but the other
concurrency levels did not improve consistently, so this report does not claim
a general causal gain.

Host-side telemetry sampled every second. Across scenarios, maximum observed
GPU memory was 15,532 MiB, utilization reached 100%, maximum temperature was
66°C, and maximum board power was 232.97 W. The Windows display and other host
consumers shared the physical GPU, so these measurements do not represent an
exclusive accelerator.

The reviewed evidence contains per-concurrency aggregates, three-run medians
and ranges, sanitized telemetry, immutable image/model identity, and SHA-256
hashes for the raw benchmark, telemetry, manifests, prompts, Compose file, and
measurement code:

- [local-rtx4080-super-vllm-summary.json](evidence/local-rtx4080-super-vllm-summary.json)
- [local-rtx4080-super-preflight.json](evidence/local-rtx4080-super-preflight.json)

Quantization quality, Kubernetes/KServe, DCGM, autoscaling, multi-GPU, and cost
remain unmeasured. `benchmarks/cost/assumptions.json` is still an illustrative
sensitivity input, not a measured RTX 4080 SUPER or cloud-GPU price result.

## Next evidence

1. Repeat CPU tests in Linux containers and the kind profile.
2. Record saturation curves at concurrency 1, 4, 8, 16, 32, and 64.
3. Separate model compute from registry lookup and serialization latency.
4. Measure KServe cold start, scale-to-zero recovery, and canary split accuracy.
5. Repeat the vLLM workload with unique representative prefixes on native
   Linux and one rented A10G/L4 for cross-hardware comparison.
6. Validate one-node failure and queue contention with two active tenants.
