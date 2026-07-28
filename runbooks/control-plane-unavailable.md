# Runbook: control-plane unavailable

## Trigger and impact

Use this runbook for `MLPlatformControlPlaneDown`, failed readiness probes, or
5xx responses from the lifecycle API. Existing KServe endpoints may continue
serving even when training, registration, or promotion is unavailable.

## Triage

1. Separate data-plane impact from control-plane impact. Test control-plane
   `/healthz` and `/readyz`, then KServe `/v2/health/live`,
   `/v2/health/ready`, and one existing inference endpoint.
2. Inspect deployment state and recent events:

   ```bash
   kubectl -n ml-platform-system get deploy,pod,svc,endpoints
   kubectl -n ml-platform-system describe deploy ml-platform
   kubectl -n ml-platform-system get events --sort-by=.lastTimestamp
   kubectl -n ml-platform-system logs deploy/ml-platform --since=30m
   ```

3. Confirm whether the failure is process crash, failed dependency, full volume,
   denied network path, missing configuration, or a bad GitOps release.
4. Check Argo CD history before changing the deployment. Correlate failure time
   with image digest and configuration revision.

## Mitigation

- Pause training and promotion submissions; do not redirect prediction traffic
  through the control API.
- For a bad release, revert Git to the last healthy digest and synchronize Argo
  CD.
- For local SQLite corruption or a full volume, keep the pod stopped and take a
  volume snapshot before repair. Never create competing writers: the reference
  Helm profile intentionally uses one replica and `Recreate`.
- For a dependency/network issue, restore the denied path or credential through
  the declared secret/workload-identity mechanism.

Do not disable readiness probes, remove policy, or scale a SQLite-backed
deployment above one replica as a shortcut.

## Verification

```bash
kubectl -n ml-platform-system rollout status deploy/ml-platform --timeout=5m
curl -fsS https://PLATFORM/readyz
curl -fsS https://PLATFORM/metrics
```

Verify a read-only status call, then one test-tenant training run. Confirm that
audit sequence numbers remain monotonic, artifact checksums validate, and
prediction endpoints were unaffected or have recovered.

## Escalation

Escalate immediately for suspected metadata loss, non-monotonic audit history,
or unauthorized configuration. Engage the storage owner for volume failures and
the release owner if rollback does not restore readiness.
