# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
vulnerability reporting for this repository and include:

- affected revision, image digest, and component;
- reproduction steps with secrets and personal data removed;
- impact and required tenant/cluster privileges;
- whether artifact integrity, isolation, or audit evidence may be affected;
- any temporary mitigation already applied.

Maintainers should acknowledge a complete report within five business days.
Response and disclosure timing depend on severity and downstream coordination.

## Supported versions

This reference project supports the current `main` branch and the most recent
tag. Dependency and controller versions are pinned for reproducibility, not a
promise of indefinite security support.

## Security boundaries

- The local API's `X-Tenant-Id` header is a demonstration boundary, not
  production authentication. A production deployment requires an OIDC-aware
  gateway and authorization derived from verified claims.
- The local SQLite registry is single-replica. Use a production database,
  backups, encryption, and workload identity for real workloads.
- No live secrets belong in this repository. Example values are placeholders.
- Production images should be digest-pinned and admitted only after signature
  verification. The lab policy does not claim supply-chain verification.
- JSON model artifacts are deliberately non-executable. Adding Pickle or another
  executable format requires a new threat analysis and sandboxing policy.
- Kubernetes namespaces are not sufficient for hostile code. Strong isolation
  can require dedicated nodes, hardened sandboxes, or separate clusters.

See [the threat model](docs/architecture/threat-model.md) for assets, actors,
controls, and residual risks.
