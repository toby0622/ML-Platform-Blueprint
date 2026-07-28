# Kubeflow training pipeline

The pipeline is an artifact-oriented implementation of:

```text
validate -> train -> evaluate + quality gate -> MLflow registration
```

Each step runs in an immutable project image and passes typed KFP artifacts.
Validation and training are cacheable; evaluation and registration deliberately
are not, so policy and registry side effects are always re-evaluated.
Registration stores the logical model name in tags and uses
`<tenant>--<model>` as the MLflow registered-model key to prevent tenant
version streams from colliding.

Compile:

```bash
python -m pip install -e '.[kfp]'
ML_PLATFORM_PIPELINE_IMAGE=ghcr.io/OWNER/ml-platform-blueprint-pipeline:TAG \
  python pipelines/training_pipeline/pipeline.py
```

The generated `pipeline.yaml` is ignored because it is a build artifact. CI
compiles the source on every change to catch DSL type errors.

Submit a run with the namespace, Pod Identity service account, tenant argument,
and S3 pipeline root bound together:

```bash
python pipelines/submit.py \
  --host http://localhost:3000 \
  --pipeline-file pipeline.yaml \
  --tenant team-a \
  --artifact-bucket REPLACE_WITH_ARTIFACT_BUCKET \
  --code-revision "$(git rev-parse HEAD)"
```

The tool always uses `ml-developer` in the selected tenant namespace and writes
KFP artifacts below `tenants/<tenant>/pipelines`. Terraform grants that identity
read/write access only within the same tenant prefix. For an in-cluster caller,
omit `--host`; never submit a `team-b` parameter into a `team-a` run manually.
