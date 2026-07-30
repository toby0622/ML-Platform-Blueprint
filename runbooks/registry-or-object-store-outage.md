# Runbook: registry or object-store outage

## Trigger and impact

Use this runbook when MLflow cannot reach PostgreSQL or object storage, artifacts
return checksum/not-found errors, pipeline registration repeatedly fails, or
KServe cannot load a referenced model.

Serving pods with an already loaded model may remain healthy. Avoid restarting
them until artifact availability is understood.

## Triage

1. Determine the failing boundary: MLflow API, PostgreSQL metadata, S3/MinIO
   object access, DNS/TLS, workload identity, or a specific artifact.
2. Inspect dependency health without printing secrets:

   ```bash
   kubectl -n ml-platform-system get pod,svc,endpoints,pvc
   kubectl -n ml-platform-system get events --sort-by=.lastTimestamp
   kubectl -n ml-platform-system logs deploy/mlflow --since=30m
   ```

3. Compare a failed URI with the registry metadata and expected SHA-256. Use a
   read-only object `HEAD` operation where available.
4. Check storage capacity, database connections, certificate expiry, bucket
   policy changes, and recent GitOps/cloud audit events.

## Mitigation

- Pause register/promote workflows while preserving completed training outputs.
- Keep healthy serving pods running; prevent voluntary restarts if their artifact
  cannot currently be reloaded.
- Restore connectivity or workload identity through declared configuration.
- If PostgreSQL is unavailable, follow the managed database recovery procedure
  and restore to a new instance from a verified point-in-time recovery target.
- If an artifact is missing or corrupt, do not rewrite its immutable version.
  Register recovered bytes as a new version only after lineage and checksum are
  independently verified.

## Verification

- MLflow readiness and a read-only run query succeed.
- A test artifact can be written, read, checksummed, and deleted in the
  designated non-production test prefix.
- A fresh pipeline registers a new version and its model card points to the same
  run and data checksum.
- A new serving pod loads a known-good artifact, becomes ready, and returns the
  expected schema.
- No previously immutable object version was overwritten.

## Escalation

Treat unexplained deletion, checksum mismatch, or access-policy broadening as a
security incident. Engage the database/storage owner before restore or failover,
and document recovery point and recovery time.
