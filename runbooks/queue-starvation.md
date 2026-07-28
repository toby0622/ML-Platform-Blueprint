# Runbook: Kueue queue starvation

## Trigger and impact

Use this runbook when `KueueWorkloadQueueStalled` fires, a tenant's admission
wait grows beyond its objective, or repeated preemption prevents useful
progress.

## Triage

1. Inspect LocalQueue and ClusterQueue status, pending workloads, flavors,
   cohort borrowing, and admission checks:

   ```bash
   kubectl get localqueues.kueue.x-k8s.io -A
   kubectl get clusterqueues.kueue.x-k8s.io
   kubectl get workloads.kueue.x-k8s.io -A
   kubectl -n TENANT describe workload WORKLOAD
   ```

2. For the oldest pending workload, read the admission condition. Distinguish:
   insufficient physical capacity, tenant nominal quota, borrowing limit,
   flavor mismatch, priority/preemption, and an unsatisfied admission check.
3. Compare requested resources with actual job use. A single oversized request
   can be impossible to fit even when aggregate quota looks free.
4. Confirm `team-a` and `team-b` share the intended `ai-teams` Cohort and that
   fair sharing is enabled.

## Mitigation

- Correct invalid requests or queue/flavor labels in the owning workload.
- Cancel abandoned workloads through their owning Job/Pipeline, not by deleting
  the Kueue Workload object directly.
- Ask owners to checkpoint or right-size oversized batch work before preempting
  useful work.
- Use the `production` priority class only for an actual service objective; do
  not relabel development work to jump the queue.
- Change nominal quota or borrowing policy only through reviewed Git, with a
  capacity calculation and an explicit tenant impact statement.

## Verification

- The oldest legitimate workload is admitted and starts.
- Queue age declines without starvation moving to another tenant.
- Borrowed resources return when nominal owners need them.
- Preemption rate stabilizes and completed-work throughput recovers.
- Git, Argo CD, and live queue policy agree.

## Escalation

Engage capacity owners when aggregate demand persistently exceeds supply.
Escalate a policy incident when priority is being abused or one tenant can evade
quota. Attach queue snapshots and the exact admission condition to the review.
