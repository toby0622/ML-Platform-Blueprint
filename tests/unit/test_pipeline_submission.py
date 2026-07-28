from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def load_submission_module():
    path = Path("pipelines/submit.py")
    spec = importlib.util.spec_from_file_location("pipeline_submission", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["pipeline_submission"] = module
    spec.loader.exec_module(module)
    return module


def test_submission_binds_namespace_identity_and_artifact_prefix() -> None:
    module = load_submission_module()
    submission = module.build_submission(
        tenant="team-a",
        model_name="churn-classifier",
        artifact_bucket="ml-platform-prod-artifacts",
        code_revision="abc123",
        tracking_uri="http://mlflow.ml-platform-system.svc.cluster.local:5000",
    )

    assert submission.namespace == "team-a"
    assert submission.service_account == "ml-developer"
    assert submission.pipeline_root == "s3://ml-platform-prod-artifacts/tenants/team-a/pipelines"
    assert submission.arguments["tenant"] == "team-a"
    assert submission.arguments["code_revision"] == "abc123"


@pytest.mark.parametrize(
    "bucket",
    ["UPPERCASE", "192.168.1.1", "invalid..bucket", "ab"],
)
def test_submission_rejects_invalid_bucket_names(bucket: str) -> None:
    module = load_submission_module()

    with pytest.raises(ValueError):
        module.build_submission(
            tenant="team-a",
            model_name="churn-classifier",
            artifact_bucket=bucket,
            code_revision="abc123",
            tracking_uri="https://mlflow.example.com",
        )
