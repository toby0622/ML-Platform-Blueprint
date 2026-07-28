# Runbook: GPU capacity unavailable

## Trigger and impact

Use this runbook when GPU workloads remain Pending, the NVIDIA device plugin is
not advertising resources, DCGM reports XID errors, or
`NvidiaGpuXidError`/`NvidiaGpuLowUtilization` fires.

## Triage

1. Check whether the workload is waiting for Kueue admission or Kubernetes
   scheduling:

   ```bash
   kubectl get workloads.kueue.x-k8s.io -A
   kubectl -n TENANT describe pod POD
   kubectl get nodes -L nvidia.com/gpu.product
   kubectl describe node NODE
   ```

2. Verify allocatable `nvidia.com/gpu`, node taints/tolerations, resource flavor,
   runtime class, image architecture, and requested GPU count.
3. Inspect GPU Operator operands and events in its namespace. Review DCGM XID,
   memory, temperature, power, and utilization around the failure.
4. For time slicing, confirm the ConfigMap and replica count match the risk
   profile. Time slicing does not provide memory or fault isolation.

## Mitigation

- For a failed node, cordon it first; stop admitting new work. Drain GPU
  workloads only after checking whether they checkpoint safely.
- Let Kueue re-admit retryable batch work on healthy capacity. Do not raise
  nominal quota when the physical resource does not exist.
- Scale the approved GPU node group only within the configured budget and quota.
- Route latency-tolerant LLM requests to an approved smaller/quantized runtime or
  CPU fallback only when that behavior is part of the service contract.
- For repeated XID errors, isolate the node and engage the cloud/hardware owner.

## Verification

- Operator operands and device plugin are ready.
- Nodes advertise the expected GPU resource and flavor label.
- A small diagnostic CUDA workload completes on the recovered node.
- Kueue admits one test workload; its GPU metric appears in DCGM/Prometheus.
- Production latency, TTFT, token throughput, and error rate return to baseline.

## Escalation

Escalate immediately for repeated XID events, thermal/power alarms, unexplained
GPU disappearance, or cross-tenant memory exposure. Record node, driver,
operator, CUDA, model-runtime, and image versions.
