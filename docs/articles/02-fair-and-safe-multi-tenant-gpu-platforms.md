# Fair and safe multi-tenant GPU platforms

GPUs turn a simple scheduling problem into an economic and reliability problem.
They are expensive, workloads can hold them for hours, model memory footprints
vary, and low utilization does not necessarily mean a job can safely share a
device. A namespace and a resource limit are necessary, but they are not a
complete multi-tenant design.

## Isolation and fairness are different controls

Kubernetes namespaces, RBAC, quotas, and NetworkPolicy answer questions such as
“may this identity create a Job here?” and “which network paths are allowed?”
They do not decide who should receive the next scarce accelerator when demand
exceeds supply.

The blueprint gives each tenant a Kueue LocalQueue backed by a ClusterQueue.
Each ClusterQueue has nominal CPU and GPU quota and joins a shared Cohort.
Nominal quota protects a baseline. Bounded borrowing lets another team use idle
capacity. Fair sharing prevents that temporary use from becoming permanent
priority when the nominal owner returns.

This creates an explicit capacity policy instead of relying on whichever pod
arrived first.

## Requests are part of the product contract

Schedulers can only make sensible decisions from declared requests. Inflated GPU
or memory requests strand capacity; requests that are too small cause eviction,
OOM, or poor latency. A platform should publish supported workload shapes,
measure actual use, and help owners right-size them.

Resource flavors connect queue policy with compatible nodes. A workload asking
for an A10 flavor should not silently land on a node with different cost or
runtime characteristics. Priority classes should represent service objectives,
not organizational seniority. Their use belongs in audit and review because
uncontrolled priority is a quota bypass.

## Time slicing is not isolation

GPU time slicing can improve utilization for suitable inference workloads, but
it does not create memory isolation or fault containment. Two tenants sharing a
device can still compete for memory bandwidth, trigger a device reset, or leak
performance information.

For untrusted workloads, sensitive models, or strict SLOs, use stronger
boundaries: dedicated devices, MIG where supported and appropriate, dedicated
node pools, or separate clusters. The correct choice follows the threat model,
not a target utilization percentage.

## Observe service and accelerator behavior together

DCGM metrics answer whether a GPU is allocated, busy, hot, memory-constrained,
or reporting XID errors. They do not answer whether an LLM service is useful.
The serving view also needs:

- time to first token (TTFT);
- inter-token latency (ITL);
- end-to-end request latency;
- prompt and generation token throughput;
- request errors and cancellations;
- queue/admission wait;
- model, quantization, tensor parallelism, and prefix-cache configuration.

Benchmarks must version those inputs. Reporting only “tokens per second” without
concurrency, prompt length, output length, hardware, and runtime configuration
is not a reproducible result.

## Convert capacity into a cost decision

Capacity planning starts with a demand model:

```text
peak generated tokens/second
  = peak requests/second × average output tokens
```

Then measure sustainable throughput at the latency objective, retain headroom
for variance and failure, and calculate the number of replicas. Cost per million
tokens should include node price, achieved—not theoretical—throughput,
utilization, storage, and platform overhead.

The included calculator keeps prices and utilization as explicit assumptions.
It never invents GPU measurements when no GPU is available. That distinction
matters: an estimate supports a planning conversation; only target-hardware
evidence supports a production capacity claim.

## Operate the policy, not just the cluster

A queue-starvation runbook should distinguish quota exhaustion from physical
capacity, flavor mismatch, admission checks, and a workload too large to fit.
An operator should cancel abandoned work through its owning Job or Pipeline, not
delete scheduler state directly. Changes to nominal quota and borrowing deserve
review because they redistribute a shared budget.

The goal is not maximum utilization at any cost. It is predictable access,
bounded failure, explainable allocation, and enough telemetry to decide when
buying or scaling capacity is actually justified.
