# ADR 0006: Reconcile signed, digest-pinned releases with GitOps

- Status: Accepted
- Date: 2026-07-28
- Owners: ML Platform team

## Context

Direct administrative changes make cluster state hard to review and reproduce.
Tags alone are mutable, and a successful container build does not establish
which source produced it or whether it was scanned.

## Decision

Use CI to test, build, scan, generate SBOM and provenance, sign images with
keyless Cosign, and publish immutable digests. Use Argo CD to reconcile declared
cluster state. The production Kyverno overlay admits platform images only when
the configured identity and issuer verify and the image is digest-pinned.

The lab overlay keeps verification disabled until a real repository identity is
configured; it must never pretend placeholder verification is security.
Application credentials are external to Git and delivered through workload
identity or a secret manager.

## Consequences

- Source, build, image, and deployment are linked by reviewable evidence.
- Rollback is a Git change to a known digest.
- Emergency cluster changes must be back-ported immediately or Argo CD will
  correct them.
- Keyless verification depends on the CI identity and transparency-log trust
  model.

## Alternatives considered

- **Manual `kubectl apply`:** rejected for normal delivery because it creates
  configuration drift.
- **Mutable image tags:** rejected because the same declaration can resolve to
  different bytes.
- **Long-lived signing keys in CI:** rejected because key custody becomes an
  additional high-value secret.
