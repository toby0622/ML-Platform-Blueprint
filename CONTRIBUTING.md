# Contributing

Thank you for improving ML Platform Blueprint. Changes should preserve the
distinction between behavior proven locally and architecture that still requires
target-environment evidence.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
```

Run the fast feedback loop:

```bash
ruff check .
ruff format --check .
mypy
python scripts/validate_repository.py
pytest --cov
```

KFP changes also require `python -m pip install -e '.[kfp]'` and:

```bash
python pipelines/training_pipeline/pipeline.py
```

Helm and Kustomize changes must render cleanly with the commands in
`.github/workflows/ci.yml`.

## Change expectations

- Add or update tests for behavior and failure paths.
- Keep tenant identity, lineage, checksums, policy decisions, and audit history
  intact across interfaces.
- Never commit credentials, tokens, kubeconfigs, live Secret payloads, or real
  user/model inputs.
- Do not invent benchmark results. Commit configuration, raw evidence, hardware
  details, and the command that produced a claim.
- Add an ADR when changing a lifecycle boundary, trust boundary, storage model,
  tenant policy, delivery policy, or core component.
- Update the relevant runbook when an alert, dependency, or mitigation changes.
- Document breaking API or artifact changes in `CHANGELOG.md`.

## Pull requests

Keep a pull request focused and describe:

1. the user or operator problem;
2. the chosen behavior and alternatives;
3. evidence from tests, rendering, benchmark, or exercise;
4. deployment and rollback implications;
5. security, tenant, cost, and compatibility impact.

Generated files such as `pipeline.yaml` and local benchmark output remain
untracked unless a reviewed evidence path explicitly includes them.
