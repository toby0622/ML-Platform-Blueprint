# Benchmarks

The benchmark suite distinguishes measured evidence from planning assumptions.
Never compare results unless model, runtime, hardware, request mix, concurrency,
warm-up, and success criteria are equivalent.

## Reference prediction API

Start a promoted local model, then run:

```bash
python benchmarks/load/run.py \
  --base-url http://127.0.0.1:8080 \
  --tenant team-a \
  --model churn-classifier \
  --requests 1000 \
  --concurrency 32 \
  --max-error-rate 0 \
  --output benchmark-results/local-cpu-load.json
```

The output contains every request sample plus availability, throughput,
status/version/route counts, and mean/p50/p95/p99/max latency. The local output
directory is ignored because results are machine-specific; reviewed summaries
belong under `docs/benchmarks/evidence/`.

## vLLM / OpenAI-compatible streaming endpoint

The runner measures TTFT, mean inter-token latency, end-to-end latency, request
throughput, and output-token throughput. On the local RTX 4080 SUPER profile,
the orchestration command restarts vLLM with the selected engine arguments,
waits for health, runs the declared warm-up and repetitions, and captures
host-side GPU telemetry:

```bash
python -m benchmarks.inference.run_local_gpu --scenario baseline
python -m benchmarks.inference.run_local_gpu --scenario prefix-cache
python -m benchmarks.inference.run_local_gpu --scenario constrained-batch
```

The local configuration uses conservative 16 GB workstation defaults in
`inference/configs-rtx4080-super.yaml`. For another target, restart vLLM with
the selected `engine_args` from `inference/configs.yaml` and invoke the
protocol-only runner directly:

```bash
python benchmarks/inference/vllm_benchmark.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model qwen2.5-1.5b-instruct \
  --prompts benchmarks/inference/prompts.json \
  --config benchmarks/inference/configs.yaml \
  --scenario baseline \
  --max-error-rate 0 \
  --output benchmark-results/vllm-baseline.json
```

Use every scenario in `inference/configs.yaml` and report the median plus
observed range across the per-run results. `mean_itl_ms` is derived from the
server-reported completion-token count and the observed streaming interval;
recording client/network placement is therefore mandatory. Capture:

- GPU, count, memory, driver, image CUDA lineage, and observed power draw/limit;
- runtime and model image digest, model revision, dtype/quantization;
- tensor parallelism, max model length, batch/token limits, prefix caching;
- prompt/output-token distribution and success/error/cancellation counts;
- Kueue wait, GPU/DCGM metrics, and serving replica count.

The RTX 4080 SUPER completed all three scenario result sets: 900 measured
requests, zero errors, and one-second GPU telemetry. The
[reviewed summary](../docs/benchmarks/evidence/local-rtx4080-super-vllm-summary.json)
contains three-run distributions and raw/source hashes without the GPU UUID.
The local runner writes a secret-free manifest with the image ID/digest and
SHA-256 hashes for configuration, prompts, measurement code, benchmark, and
telemetry artifacts. Unsupported WSL NVML fields remain missing data and are
never presented as zero.

## Capacity and cost

`cost/assumptions.json` contains an illustrative—not measured—scenario. Replace
price, achieved output-token throughput, and average output tokens per request
with current provider pricing and target-hardware evidence, then run:

```bash
python benchmarks/cost/calculate.py \
  --assumptions benchmarks/cost/assumptions.json \
  --output benchmark-results/cost.json
```

Do not remove the planning warning from generated output. Cost per token is
reported per million **output** tokens because that is the measured throughput
denominator. It remains sensitive to input/output mix, achieved utilization,
headroom, failure capacity, storage, and platform overhead.
