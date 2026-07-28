# GPU plane

The GPU overlay is intentionally optional. It installs the NVIDIA GPU Operator
with Device Plugin, GPU Feature Discovery, and DCGM Exporter. Exclusive GPU
allocation is the safe default. Time-slicing is provided only as an opt-in lab
profile; production teams must decide between exclusive GPUs, MIG, and
time-slicing based on isolation and workload behavior.

Apply `device-plugin-config.yaml` before the Helm release. A node must also be
labelled for the matching Kueue `ResourceFlavor`:

```bash
kubectl label node GPU_NODE ml-platform.io/accelerator=nvidia-a10
kubectl taint node GPU_NODE nvidia.com/gpu=present:NoSchedule
```

To opt one lab node into time-slicing:

```bash
kubectl label node GPU_NODE \
  nvidia.com/device-plugin.config=time-slicing --overwrite
```

Because `renameByDefault` is enabled, shared capacity is advertised as
`nvidia.com/gpu.shared`. This makes sharing visible in workload and quota
contracts. Add a dedicated Kueue flavor and tenant quota for that resource
before admitting shared jobs; do not count the same physical GPU as both an
exclusive and shared pool. The vLLM example requests an exclusive
`nvidia.com/gpu` and is intentionally not placed on the time-sliced profile.

Do not enable the GPU plane on CPU-only kind clusters.

## RTX 4080 SUPER workstation profile

The Windows workstation path does not install this Helm overlay. It runs the
pinned vLLM Compose service through Docker Desktop's WSL 2 Linux engine and
uses host-side `nvidia-smi` telemetry. See
[`docs/local-gpu.md`](../../docs/local-gpu.md).

This separation is intentional:

- WSL receives the CUDA interface from the Windows display driver, so the
  default `driver.enabled: true` Operator values do not apply;
- Docker Desktop uses WSL GPU paravirtualization rather than native Linux PCIe
  passthrough;
- NVML fields can be incomplete under WSL, so DCGM is not a local acceptance
  gate;
- GeForce RTX 4080 SUPER has no supported MIG profile for this project;
- Compose exposes one GPU to vLLM but cannot exclude WDDM or other host
  consumers; the native-Linux KServe overlay is capped at one replica.

For a native Linux Kubernetes node containing a 16 GB Ada GPU, install and
validate the GPU Operator/device plugin for that host, then use the repository's
stable node label:

```bash
kubectl label node GPU_NODE \
  ml-platform.io/accelerator=nvidia-ada-16gb --overwrite
kubectl taint node GPU_NODE nvidia.com/gpu=present:NoSchedule
kubectl kustomize serving/vllm/overlays/rtx4080-super
```

Rendering the overlay is a static check. It does not prove that a WSL, kind, or
native Linux cluster exposes the physical GPU.
