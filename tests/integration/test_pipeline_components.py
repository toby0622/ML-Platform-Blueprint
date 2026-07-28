from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from mlflow import MlflowClient

from ml_platform_blueprint.pipeline_components import main


def test_artifact_oriented_pipeline_components(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "dataset.npz"
    metadata = tmp_path / "dataset.json"
    model = tmp_path / "model.json"
    evaluation_data = tmp_path / "evaluation.npz"
    parameters = tmp_path / "parameters.json"
    metrics = tmp_path / "metrics.json"

    assert (
        main(
            [
                "validate",
                "--samples",
                "800",
                "--data-seed",
                "42",
                "--output",
                str(dataset),
                "--metadata",
                str(metadata),
            ]
        )
        == 0
    )
    validation_output = json.loads(capsys.readouterr().out)
    assert validation_output["samples"] == 800

    assert (
        main(
            [
                "train",
                "--dataset",
                str(dataset),
                "--dataset-metadata",
                str(metadata),
                "--model",
                str(model),
                "--evaluation-data",
                str(evaluation_data),
                "--parameters",
                str(parameters),
                "--split-seed",
                "42",
                "--test-fraction",
                "0.2",
                "--learning-rate",
                "0.12",
                "--epochs",
                "700",
                "--l2",
                "0.01",
                "--decision-threshold",
                "0.5",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["epochs"] == 700

    assert (
        main(
            [
                "evaluate",
                "--model",
                str(model),
                "--evaluation-data",
                str(evaluation_data),
                "--metrics",
                str(metrics),
                "--enforce-gate",
            ]
        )
        == 0
    )
    evaluation = json.loads(capsys.readouterr().out)
    assert evaluation["quality_gate"]["accepted"] is True
    assert json.loads(metrics.read_text(encoding="utf-8")) == evaluation


def test_pipeline_component_reports_gate_and_optional_dependency_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "dataset.npz"
    metadata = tmp_path / "dataset.json"
    model = tmp_path / "model.json"
    evaluation_data = tmp_path / "evaluation.npz"
    parameters = tmp_path / "parameters.json"
    metrics = tmp_path / "metrics.json"
    registration = tmp_path / "registration.json"

    assert (
        main(
            [
                "validate",
                "--samples",
                "800",
                "--data-seed",
                "42",
                "--output",
                str(dataset),
                "--metadata",
                str(metadata),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "train",
                "--dataset",
                str(dataset),
                "--dataset-metadata",
                str(metadata),
                "--model",
                str(model),
                "--evaluation-data",
                str(evaluation_data),
                "--parameters",
                str(parameters),
                "--split-seed",
                "42",
                "--test-fraction",
                "0.2",
                "--learning-rate",
                "0.12",
                "--epochs",
                "700",
                "--l2",
                "0.01",
                "--decision-threshold",
                "0.99",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "evaluate",
                "--model",
                str(model),
                "--evaluation-data",
                str(evaluation_data),
                "--metrics",
                str(metrics),
                "--enforce-gate",
            ]
        )
        == 1
    )
    assert "RuntimeError" in capsys.readouterr().err

    # Registration requires the optional MLflow extra and must fail clearly when
    # that dependency is absent from the lightweight development profile.
    monkeypatch.setitem(sys.modules, "mlflow", None)
    assert (
        main(
            [
                "register",
                "--model",
                str(model),
                "--parameters",
                str(parameters),
                "--metrics",
                str(metrics),
                "--registration",
                str(registration),
                "--tracking-uri",
                "http://127.0.0.1:5000",
                "--experiment",
                "test",
                "--tenant",
                "team-a",
                "--model-name",
                "churn",
                "--pipeline-run-id",
                "pipeline-test",
                "--code-revision",
                "test",
                "--dataset-metadata",
                str(metadata),
            ]
        )
        == 1
    )
    assert "mlflow extra" in capsys.readouterr().err


@pytest.mark.integration
def test_pipeline_registers_tenant_qualified_model_in_mlflow(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = tmp_path / "dataset.npz"
    metadata = tmp_path / "dataset.json"
    model = tmp_path / "model.json"
    evaluation_data = tmp_path / "evaluation.npz"
    parameters = tmp_path / "parameters.json"
    metrics = tmp_path / "metrics.json"
    registration = tmp_path / "registration.json"

    assert (
        main(
            [
                "validate",
                "--samples",
                "800",
                "--data-seed",
                "42",
                "--output",
                str(dataset),
                "--metadata",
                str(metadata),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "train",
                "--dataset",
                str(dataset),
                "--dataset-metadata",
                str(metadata),
                "--model",
                str(model),
                "--evaluation-data",
                str(evaluation_data),
                "--parameters",
                str(parameters),
                "--split-seed",
                "42",
                "--test-fraction",
                "0.2",
                "--learning-rate",
                "0.12",
                "--epochs",
                "700",
                "--l2",
                "0.01",
                "--decision-threshold",
                "0.5",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "evaluate",
                "--model",
                str(model),
                "--evaluation-data",
                str(evaluation_data),
                "--metrics",
                str(metrics),
                "--enforce-gate",
            ]
        )
        == 0
    )
    capsys.readouterr()

    tracking_uri = f"sqlite:///{(tmp_path / 'pipeline-mlflow.db').as_posix()}"
    experiment = "pipeline-registration-test"
    client = MlflowClient(tracking_uri=tracking_uri)
    client.create_experiment(
        experiment,
        artifact_location=(tmp_path / "mlflow-artifacts").as_uri(),
    )
    register_args = [
        "register",
        "--model",
        str(model),
        "--parameters",
        str(parameters),
        "--metrics",
        str(metrics),
        "--registration",
        str(registration),
        "--tracking-uri",
        tracking_uri,
        "--experiment",
        experiment,
        "--tenant",
        "team-a",
        "--model-name",
        "churn",
        "--pipeline-run-id",
        "pipeline-registration-run",
        "--code-revision",
        "pipeline-registration-test",
        "--dataset-metadata",
        str(metadata),
    ]
    assert main(register_args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["registered_model_name"] == "team-a--churn"
    assert json.loads(registration.read_text(encoding="utf-8")) == result

    registered = client.get_registered_model("team-a--churn")
    assert registered.name == "team-a--churn"
    version = client.get_model_version("team-a--churn", result["model_version"])
    assert version.tags["tenant"] == "team-a"
    assert version.tags["quality_gate"] == "passed"

    second_args = register_args.copy()
    second_args[second_args.index("pipeline-registration-run")] = "pipeline-registration-run-2"
    assert main(second_args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["model_version"] == 2
