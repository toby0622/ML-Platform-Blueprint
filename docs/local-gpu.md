# Local NVIDIA GPU profile

This profile turns one NVIDIA workstation GPU into a reproducible vLLM
development and benchmark target. It is intentionally separate from the
production-style GPU Operator profile.

The inventory, CUDA container passthrough, vLLM endpoint, chat completion, and
three benchmark scenarios were executed on:

| Dimension | Observed value |
|---|---|
| GPU | NVIDIA GeForce RTX 4080 SUPER |
| VRAM | 16,376 MiB |
| Compute capability | 8.9 (Ada) |
| Windows driver | 610.74 |
| Allocation | One GPU exposed to the container; physical GPU shared with WDDM |

The reviewed result contains 900 successful measured requests and GPU telemetry:
[local-rtx4080-super-vllm-summary.json](benchmarks/evidence/local-rtx4080-super-vllm-summary.json).
It is a local WSL 2 result, not a datacenter or Kubernetes capacity claim.

## Runtime decision

vLLM supports Linux and does not have a native Windows runtime. On a Windows
workstation, use Docker Desktop with its WSL 2 Linux engine. Do not install a
second Linux NVIDIA display driver inside WSL; the Windows driver exposes CUDA
to WSL.

The local path is:

```text
Windows NVIDIA driver
        |
        v
WSL 2 / Docker Desktop Linux engine
        |
        v
vllm/vllm-openai:v0.23.0 (digest pinned)
        |
        v
OpenAI-compatible API on localhost:8000
```

The official references for this decision are the
[vLLM GPU installation guide](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/),
[Docker Desktop GPU guide](https://docs.docker.com/desktop/features/gpu/), and
[NVIDIA CUDA on WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html).

## One-time workstation setup

The validated host uses Docker Desktop 4.84.0, Engine 29.6.2, Compose 5.3.1,
and its WSL 2 Linux engine. On another workstation, complete these host-level
steps before starting vLLM.

1. In an elevated PowerShell window, update WSL and reboot if Windows requests
   it:

   ```powershell
   wsl --update
   wsl --status
   ```

   A user Ubuntu distribution is optional for the PowerShell/Compose workflow.
   Install one with `wsl --install -d Ubuntu-24.04` only if a separate Linux
   development shell is desired.

2. Install Docker Desktop, select the WSL 2 engine, and use Linux containers.
   Do not also operate a second Docker daemon inside a user distribution.

3. Start Docker Desktop and run the repository's read-only preflight:

   ```powershell
   python scripts/gpu_preflight.py
   ```

   If Docker Desktop was installed after the terminal opened, restart the
   terminal. The repository also discovers the per-user executable under
   `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe`.

The preflight does not pull an image or start a container. It checks GPU
inventory, compute capability, VRAM, Docker Compose v2, a reachable Linux
daemon, GPU flags/runtime declarations, and WSL 2. It exits nonzero and returns
stable blocking reason codes until every prerequisite is visible.

If Docker Engine is intentionally managed inside WSL instead of Docker Desktop,
follow the
[NVIDIA Container Toolkit installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
and configure that one daemon with `nvidia-ctk`. Do not maintain both runtime
paths.

## Start the endpoint

Copy the example environment file and keep real tokens out of Git:

```powershell
Copy-Item .env.example .env
docker compose --file compose.gpu.yaml up --detach
docker compose --file compose.gpu.yaml ps
docker compose --file compose.gpu.yaml logs --follow vllm
```

The public default model needs no token. If a gated model is used, treat
`HF_TOKEN` as a short-lived, read-only local credential: Docker administrators
can inspect container environment values. Use a Compose secret/file override
before adapting this profile to a shared machine.

The first run downloads the digest-pinned image and public model. The profile
disables Hugging Face Xet by default because this host observed repeated CDN
range-request failures; `HF_HUB_DISABLE_XET=0` with fixed concurrency 8 is the
documented faster retry. The service is ready when
`http://127.0.0.1:8000/health` returns HTTP 200. The port is bound to loopback,
not every LAN interface. Test the OpenAI-compatible API:

```powershell
$body = @{
  model = "qwen2.5-1.5b-instruct"
  messages = @(@{ role = "user"; content = "Explain prefix caching in one sentence." })
  max_tokens = 64
  temperature = 0
} | ConvertTo-Json -Depth 4

Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/v1/chat/completions `
  -Method Post `
  -ContentType application/json `
  -Body $body
```

Stop only this profile when finished:

```powershell
docker compose --file compose.gpu.yaml down
```

The named Hugging Face cache volume remains for future starts. Delete it only
when intentionally reclaiming the downloaded model storage.

## RTX 4080 SUPER defaults

The defaults favor a repeatable first run over maximum utilization:
The [Qwen model card](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)
documents the Apache-2.0 license and 1.54B parameter count.

| Setting | Default | Reason |
|---|---:|---|
| Model | `Qwen/Qwen2.5-1.5B-Instruct` at `989aa798...` | 1.54B, Apache-2.0, inside the planned 1-3B range |
| vLLM image | `vllm/vllm-openai:v0.23.0@sha256:6d8429e...` | Immutable CUDA 13 runtime instead of `latest` |
| GPU memory utilization | `0.75` | Leaves WDDM/display headroom on a 16 GB GeForce card |
| Max model length | 4,096 | Bounded KV-cache demand for first validation |
| Max concurrent sequences | 32 | Bounded scheduler pressure |
| Chunked prefill | enabled | Controls long-prefill scheduling pressure |
| Prefix caching | disabled in baseline | Allows a controlled on/off comparison |
| GPU count | 1 selected | Dedicated benchmark window; WDDM still shares the physical GPU |

After closing other GPU-heavy applications, increase memory utilization in
small steps and treat OOM as a failed configuration, not a result to omit.
Never compare runs with materially different desktop GPU load.

All values can be changed in `.env`. For an AWQ experiment, use an equivalently
licensed quantized model and record the different model artifact explicitly:

```powershell
$env:VLLM_MODEL = "Qwen/Qwen2.5-1.5B-Instruct-AWQ"
$env:VLLM_MODEL_REVISION = ""
$env:VLLM_SERVED_MODEL_NAME = "qwen2.5-1.5b-instruct-awq"
$env:VLLM_QUANTIZATION = "awq"
python -m benchmarks.inference.run_local_gpu `
  --scenario baseline `
  --output benchmark-results/vllm-awq-baseline.json `
  --telemetry-output benchmark-results/vllm-awq-baseline-gpu.json
```

Do not present unquantized and AWQ numbers as a quality-neutral speed comparison
without a separate output-quality evaluation.

## Reproducible benchmark

The local runner applies the selected engine scenario, recreates only the vLLM
service, waits for health, runs the streaming benchmark, and samples host-side
GPU telemetry until the load completes:

```powershell
python -m benchmarks.inference.run_local_gpu --scenario baseline
python -m benchmarks.inference.run_local_gpu --scenario prefix-cache
python -m benchmarks.inference.run_local_gpu --scenario constrained-batch
```

Each scenario runs three repetitions at concurrency 1, 2, 4, 8, and 16 by
default. The quality gate must pass globally and for every run/concurrency
slice. Outputs remain under the ignored `benchmark-results/` directory:

- `vllm-SCENARIO.json`: TTFT, ITL, end-to-end latency, request and token
  throughput, errors, per-run results, and raw request samples;
- `vllm-SCENARIO-gpu-telemetry.json`: raw `nvidia-smi` samples plus per-GPU
  p50/p95/max memory, utilization, temperature, and power summaries;
- `vllm-SCENARIO-manifest.json`: scenario and model settings, SHA-256 hashes,
  container image ID and registry digest, prompt/driver/wrapper/configuration
  hashes, artifact hashes, telemetry status, and benchmark exit status. It
  intentionally excludes `HF_TOKEN`.

The completed run measured 300 requests per scenario with zero errors. At
concurrency 16, baseline output throughput was 1,861.45 tokens/s with p95 TTFT
61.20 ms; the 128-token constrained batch produced 1,640.26 tokens/s with p95
TTFT 122.30 ms. See the
[benchmark report](benchmarks/report.md) and
[machine-readable evidence](benchmarks/evidence/local-rtx4080-super-vllm-summary.json)
for all levels, three-run distributions, and telemetry.

For an inventory or manually timed experiment, use the collector directly:

```powershell
python benchmarks/gpu/collect.py `
  --duration 300 `
  --interval 1 `
  --output benchmark-results/gpu-telemetry.json
```

WSL exposes a limited NVML surface. Unsupported fields are preserved as JSON
`null`; the collector never replaces them with zero. Full DCGM validation
remains a native-Linux or cloud GPU-node exercise.

The evidence publisher verifies every available raw artifact hash and removes
the GPU UUID before publishing:

```powershell
python -m benchmarks.inference.publish_evidence
```

Record background workload controls, prompt set, warm-up, run count, and
observed variance. A single best run is not an acceptable result.

## Kubernetes reference overlay

The workstation Compose path is the supported local execution path. For a
native Linux Kubernetes lab node containing one 16 GB Ada GPU, label and taint
the node, then render the KServe overlay:

```bash
kubectl label node GPU_NODE \
  ml-platform.io/accelerator=nvidia-ada-16gb --overwrite
kubectl taint node GPU_NODE nvidia.com/gpu=present:NoSchedule
kubectl kustomize serving/vllm/overlays/rtx4080-super
```

The overlay requests one exclusive `nvidia.com/gpu`, pins the KServe runtime
version, and fixes both minimum and maximum replicas at one. Applying it still
requires KServe and a working NVIDIA device plugin on the target Linux cluster.
Do not install the repository's default GPU Operator values into WSL: they
manage a Linux driver and enable DCGM assumptions that do not match WSL
GPU paravirtualization.

## Troubleshooting order

1. `nvidia-smi` cannot see the GPU: fix the Windows NVIDIA driver first.
2. Preflight reports `wsl.*`: install/update a WSL 2 distribution.
3. Preflight reports `docker.*`: start Docker Desktop, select Linux containers,
   and verify its WSL 2 engine.
4. Container reports no CUDA device: verify Docker GPU support before changing
   model arguments.
5. vLLM exits with OOM: close desktop GPU consumers, lower
   `VLLM_GPU_MEMORY_UTILIZATION`, context length, or sequence count.
6. Model download fails: verify HTTPS, disk space, model ID/license, and
   `HF_TOKEN` only when the model is gated.
7. Telemetry fields are `null`: confirm the field is exposed by NVML under WSL;
   do not convert unsupported values to zero.
