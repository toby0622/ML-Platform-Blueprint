# ADR 0004: Separate registration, promotion, and traffic

- Status: Accepted
- Date: 2026-07-28
- Owners: ML Platform team

## Context

A successfully trained model is not necessarily safe to serve. Conflating
registration with production deployment makes rollback ambiguous and removes
the opportunity to compare offline quality and online service indicators.

## Decision

Represent model delivery as explicit, audited transitions:

`registered -> production` for the first qualifying version, and
`registered -> canary -> production | rolled_back` thereafter.

The offline gate checks accuracy, F1, ROC-AUC, Brier score, and evaluation sample
count. The online gate compares candidate error rate and p95 latency with the
stable version after a minimum candidate sample count. Failed online policy
atomically removes candidate traffic. Manual rollback selects an immutable,
known-good version.

Canary routing is a deterministic hash of tenant and request identity so retries
do not oscillate between versions.

## Consequences

- Every production change has an attributable policy decision.
- Offline quality and online reliability remain separate signals.
- First deployment cannot perform a stable-versus-candidate comparison and uses
  the offline gate plus readiness as its promotion contract.
- Business-specific fairness or drift checks must be added before this policy is
  used for regulated decisions.

## Alternatives considered

- **Deploy after training success:** rejected because execution success is not a
  quality signal.
- **Random canary routing:** rejected because retries and debugging would be less
  reproducible.
- **Mutable model alias only:** rejected because an alias without transition
  history is insufficient audit evidence.
