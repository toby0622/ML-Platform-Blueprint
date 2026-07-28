# ADR 0008: Separate the consumer-GPU execution profile from the cluster GPU plane

- Status: Accepted
- Date: 2026-07-28
- Owners: ML Platform team

## Context

The project now has access to one Windows workstation with an NVIDIA GeForce RTX
4080 SUPER and 16 GB VRAM. The existing GPU plane assumes a Linux Kubernetes
node, GPU Operator, device-plugin scheduling, and DCGM. Applying those
assumptions directly to WSL GPU paravirtualization would make local validation
fragile and overstate DCGM and cluster behavior.

vLLM requires Linux. The workstation GPU is also used by WDDM and desktop
applications, so the inference process cannot safely assume datacenter-style
exclusive access to all VRAM even when Docker reserves the one physical GPU.

## Decision

Maintain two related but distinct GPU paths:

- use a pinned vLLM Linux container under Docker Desktop's WSL 2 engine for
  workstation execution and benchmark evidence;
- retain GPU Operator, DCGM, Kueue, and KServe as the cluster reference path,
  with a single-replica Ada overlay for a compatible native Linux node.

The workstation path starts with 75% vLLM memory utilization, a public
Apache-2.0 1.5B model, 4,096-token context, one GPU exposed to the container,
and host-side `nvidia-smi` sampling. Compose does not exclude WDDM or other host
consumers, so comparisons use a dedicated benchmark window. Missing WSL NVML
fields remain missing data. Scenario configuration is versioned and the
benchmark runner restarts vLLM before each comparison.

## Consequences

- The available RTX 4080 SUPER can produce real TTFT, ITL, throughput, memory,
  power, temperature, prefix-cache, batching, and quantization evidence.
- Contributors get a small, licensed default model with enough VRAM headroom
  for Windows display activity.
- Local evidence does not prove GPU Operator, Kueue, KServe, autoscaling, MIG,
  time-slicing, DCGM, multi-GPU, or failure-domain behavior.
- The same OpenAI-compatible protocol and scenario vocabulary connect the local
  result to the cluster deployment without pretending the runtimes are
  identical.

## Alternatives considered

- **Run vLLM natively on Windows:** rejected because upstream vLLM does not
  support a native Windows runtime.
- **Run a full GPU Kubernetes stack inside Docker Desktop:** rejected as the
  default because nested device exposure and WSL GPU-PV do not validate a
  production Linux GPU node.
- **Keep renting an A10G as the only benchmark path:** rejected because owned
  hardware now provides repeatable evidence without hourly cost; a cloud GPU
  remains useful for cross-hardware comparison.
- **Use 90-95% VRAM immediately:** rejected because the same GeForce adapter
  services the Windows desktop and currently has non-vLLM consumers.
