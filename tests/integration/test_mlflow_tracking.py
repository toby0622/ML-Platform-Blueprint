from __future__ import annotations

import json
from pathlib import Path

import pytest
from mlflow import MlflowClient

from ml_platform_blueprint.config import Settings
from ml_platform_blueprint.service import PlatformService


@pytest.mark.integration
def test_training_mirrors_run_scoped_evidence_to_mlflow(tmp_path: Path) -> None:
    tracking_uri = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"
    service = PlatformService(
        Settings(
            state_dir=tmp_path / "platform",
            code_revision="mlflow-integration-test",
            mlflow_tracking_uri=tracking_uri,
            mlflow_experiment="ml-platform-integration",
            environment="test",
        )
    )

    result = service.train_and_register(tenant="team-a", model_name="churn")

    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name("ml-platform-integration")
    assert experiment is not None
    runs = client.search_runs([experiment.experiment_id])
    assert len(runs) == 1
    run = runs[0]
    assert run.info.status == "FINISHED"
    assert run.data.tags["platform.run_id"] == result["run_id"]
    assert run.data.tags["platform.tenant"] == "team-a"
    assert run.data.params["epochs"] == "700"
    assert run.data.metrics["roc_auc"] >= 0.78

    local_snapshot = json.loads(
        (tmp_path / "platform" / "tracking" / f"{result['run_id']}.json").read_text(
            encoding="utf-8"
        )
    )
    assert local_snapshot["status"] == "FINISHED"
