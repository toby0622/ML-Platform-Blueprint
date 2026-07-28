# Runbook: model rollout degradation

## Trigger and impact

Use this runbook when a candidate increases prediction errors or latency,
returns implausible outputs, fails its online gate, or when
`MLPlatformPredictionErrorBudgetFastBurn` or
`MLPlatformPredictionErrorBudgetSlowBurn` fires during a rollout.

The safest default is to stop candidate traffic while preserving the candidate
artifact and all evidence.

## Triage

1. Identify tenant, model, stable version, candidate version, rollout start, and
   actor from the audit endpoint:

   ```bash
   curl -sS "https://PLATFORM/v1/tenants/TENANT/models/MODEL/audit" \
     -H "X-Tenant-Id: TENANT"
   curl -sS "https://PLATFORM/v1/tenants/TENANT/models/MODEL/deployment" \
     -H "X-Tenant-Id: TENANT"
   ```

2. Compare stable and candidate request count, outcome, and latency. Confirm
   whether the regression is isolated to a route, input cohort, or dependency.
3. Inspect the candidate model card and metadata checksum. A checksum failure is
   a supply-chain incident; stop traffic and escalate immediately.
4. Freeze further promotions for the affected model. Do not stop unrelated
   tenant traffic.

## Mitigation

If a candidate exists, atomically remove its traffic:

```bash
curl -sS -X POST \
  "https://PLATFORM/v1/tenants/TENANT/models/MODEL/deployment/rollback" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: TENANT" \
  -d '{"actor":"oncall","reason":"INCIDENT_ID: candidate regression"}'
```

If both stable and candidate are unhealthy, select a verified prior immutable
version through the same rollback API. Do not edit an artifact or reuse a
version number. For a KServe rollout, revert the GitOps declaration to the
known-good digest and set canary traffic to zero, then let Argo CD reconcile.

## Verification

- The deployment endpoint has no candidate and names the intended stable version.
- Candidate-routed request growth stops.
- Availability and latency recover for at least two evaluation windows.
- A known prediction fixture returns the expected schema and plausible score.
- The audit event contains incident ID, actor, source and target versions.
- Argo CD reports `Synced` and `Healthy`; no manual drift remains.

## Escalation and follow-up

Escalate to the model owner for cohort-specific quality issues, to platform
security for checksum/signature failures, and to the serving owner if the
known-good version is also unhealthy. Preserve request samples only after
redaction. Open follow-ups for a missing gate, alert, test fixture, or capacity
limit and attach the promotion decision to the postmortem.
