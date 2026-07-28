# Synthetic postmortem: canary latency regression

> This is a deliberately constructed exercise. It did not affect real users.
> Times, request volumes, and people are synthetic; the control and evidence
> paths are implemented by this repository.

- Exercise date: 2026-07-28
- Severity: SEV-2 exercise
- Duration: 18 minutes
- Affected service: `team-a/churn-classifier`
- Primary signal: candidate p95 latency and error-rate gate
- Authors: ML Platform team
- Status: Closed with follow-ups

## Executive summary

Version 2 passed the offline model-quality gate and entered a 10% canary.
Its artifact was valid, but an added feature-normalization branch amplified
CPU work for records with many missing values. Candidate p95 latency rose to
2.1 times stable and upstream callers began timing out. The online gate rejected
the candidate after its minimum sample window and atomically returned all
traffic to version 1. No artifact or metadata was lost, and version 1 remained
healthy.

The platform behaved safely, but the alert reached the on-call four minutes
after the first client timeout. The benchmark fixture also lacked the
missing-value-heavy cohort that triggered the regression.

## Impact

- 1,204 requests entered during the exercise window.
- 121 were deterministically assigned to the candidate.
- 9 candidate requests exceeded the caller timeout and were observed as errors.
- Stable traffic and other tenants were unaffected.
- No incorrect promotion was finalized.
- No manual mutation of model metadata or serving artifacts occurred.

## Detection

The first indication was a caller timeout at 10:04. The multi-window
`MLPlatformPredictionErrorBudgetFastBurn` alert fired at 10:08. At 10:09 the
promotion controller had enough candidate
samples to evaluate the online gate and recorded:

```json
{
  "decision": "rollback",
  "candidate_version": 2,
  "stable_version": 1,
  "candidate_samples": 100,
  "error_rate_delta": 0.061,
  "allowed_error_rate_delta": 0.02,
  "latency_ratio": 2.1,
  "allowed_latency_ratio": 1.25
}
```

## Timeline

All times are Asia/Taipei (UTC+08:00).

| Time | Event |
|---|---|
| 10:00 | CI evidence and offline metrics for version 2 pass. |
| 10:02 | Operator starts a 10% canary; audit event records actor and reason. |
| 10:04 | First missing-value-heavy candidate request exceeds caller timeout. |
| 10:08 | Error-budget burn alert pages the platform on-call. |
| 10:09 | Candidate reaches 100 samples; online gate rejects it and sets canary traffic to zero. |
| 10:11 | On-call confirms version 1 is the only active route. |
| 10:14 | Latency and error rate recover to baseline. |
| 10:18 | Incident is downgraded; evidence collection begins. |

## Root cause

Version 2 introduced per-request normalization that repeatedly allocated arrays
for missing values. The offline evaluation measured predictive quality but did
not execute a representative serving load. The load-test input generator used
uniform well-formed examples and therefore did not include the expensive cohort.

## Contributing factors

- Performance validation was a release report, not a required promotion input.
- The caller timeout was shorter than the first alert window.
- The dashboard showed aggregate latency first; per-version latency required a
  drill-down.
- The model owner interpreted an offline quality pass as evidence of deployment
  readiness, despite the documented distinction.

## What worked

- Registration did not automatically grant traffic.
- Hash-based routing limited exposure and made affected requests reproducible.
- The minimum-sample online gate made an automatic, explainable decision.
- Rollback removed candidate traffic without deleting the version or its lineage.
- Version, route, metrics, thresholds, actor, and result were present in audit
  evidence.
- Tenant and stable traffic isolation limited impact.

## What did not work

- Client impact preceded the page by four minutes.
- Pre-promotion inputs did not represent missing-value distribution.
- The dashboard default obscured the version split.
- No automatic load-test evidence was attached to the promotion request.

## Corrective actions

| Action | Owner | Priority | Due | Verification |
|---|---|---:|---|---|
| Add missing-value cohorts to load fixtures | Model platform | P0 | 2026-08-04 | Regression test reproduces old latency path |
| Require a versioned CPU load report before canary | Release platform | P0 | 2026-08-11 | Promotion API rejects missing evidence |
| Add a fast candidate timeout/error alert | SRE | P1 | 2026-08-04 | Alert unit test and game day |
| Put per-version p95 on dashboard overview | Observability | P1 | 2026-08-04 | Dashboard screenshot review |
| Precompute normalization state at model load | Model owner | P1 | 2026-08-11 | p95 stays within 1.25x stable |
| Repeat this game day on KServe profile | Platform team | P2 | 2026-08-25 | Exercise record and audit export |

## Lessons

Model quality, serving reliability, and business correctness are independent
release dimensions. A safe platform makes each dimension explicit and preserves
the evidence needed to explain a decision after the fact.
