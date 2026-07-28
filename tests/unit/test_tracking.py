from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ml_platform_blueprint.config import Settings
from ml_platform_blueprint.service import PlatformService
from ml_platform_blueprint.tracking import (
    LocalTracker,
    MlflowMirrorTracker,
    create_tracker,
)


class FakeMlflowClient:
    def __init__(self, tracking_uri: str | None) -> None:
        self.tracking_uri = tracking_uri
        self.parameters: list[tuple[str, str, Any]] = []
        self.metrics: list[tuple[str, str, float]] = []
        self.terminated: list[tuple[str, str]] = []
        self.runs: list[dict[str, Any]] = []

    def get_experiment_by_name(self, _name: str) -> None:
        return None

    def create_experiment(self, _name: str) -> str:
        return "experiment-1"

    def create_run(self, *, experiment_id: str, tags: dict[str, str]) -> Any:
        remote_id = f"remote-{len(self.runs) + 1}"
        self.runs.append({"experiment_id": experiment_id, "tags": tags, "run_id": remote_id})
        return SimpleNamespace(info=SimpleNamespace(run_id=remote_id))

    def log_param(self, run_id: str, key: str, value: Any) -> None:
        self.parameters.append((run_id, key, value))

    def log_metric(self, run_id: str, key: str, value: float) -> None:
        self.metrics.append((run_id, key, value))

    def set_terminated(self, run_id: str, *, status: str) -> None:
        self.terminated.append((run_id, status))


def test_mlflow_tracker_uses_run_scoped_client_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clients: list[FakeMlflowClient] = []

    def client_factory(*, tracking_uri: str | None) -> FakeMlflowClient:
        client = FakeMlflowClient(tracking_uri)
        clients.append(client)
        return client

    monkeypatch.setitem(
        sys.modules,
        "mlflow",
        SimpleNamespace(MlflowClient=client_factory),
    )
    local = LocalTracker(tmp_path)
    tracker = MlflowMirrorTracker(
        local,
        Settings(
            state_dir=tmp_path,
            mlflow_tracking_uri="http://mlflow.test",
            mlflow_experiment="unit-test",
        ),
    )
    tracker.start(
        run_id="run-a",
        tenant="team-a",
        model_name="churn",
        tags={"code_revision": "test"},
    )
    tracker.start(
        run_id="run-b",
        tenant="team-a",
        model_name="churn",
        tags={"code_revision": "test"},
    )
    tracker.log_parameters("run-a", {"epochs": 10})
    tracker.log_metrics("run-b", {"accuracy": 0.9})
    tracker.finish("run-a", "FINISHED")
    tracker.finish("run-b", "FAILED")

    client = clients[0]
    assert client.tracking_uri == "http://mlflow.test"
    assert client.parameters == [("remote-1", "epochs", 10)]
    assert client.metrics == [("remote-2", "accuracy", 0.9)]
    assert client.terminated == [
        ("remote-1", "FINISHED"),
        ("remote-2", "FAILED"),
    ]
    assert json.loads((tmp_path / "tracking" / "run-a.json").read_text())["status"] == "FINISHED"


def test_create_tracker_selects_local_or_reports_missing_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert isinstance(create_tracker(Settings(state_dir=tmp_path)), LocalTracker)
    monkeypatch.setitem(sys.modules, "mlflow", None)
    with pytest.raises(RuntimeError, match="mlflow extra"):
        create_tracker(
            Settings(
                state_dir=tmp_path,
                mlflow_tracking_uri="http://mlflow.test",
            )
        )


class TerminalFailureTracker:
    def start(self, **_values: Any) -> None:
        pass

    def log_parameters(self, _run_id: str, _parameters: dict[str, Any]) -> None:
        pass

    def log_metrics(self, _run_id: str, _metrics: dict[str, float]) -> None:
        pass

    def finish(self, _run_id: str, _status: str) -> None:
        raise RuntimeError("remote tracking unavailable")


def test_tracking_terminal_failure_does_not_invalidate_registered_model(
    tmp_path: Path,
) -> None:
    service = PlatformService(
        Settings(state_dir=tmp_path, code_revision="tracking-test"),
        tracker=TerminalFailureTracker(),
    )

    result = service.train_and_register(tenant="team-a", model_name="churn")

    assert result["model_version"]["version"] == 1
    assert service.registry.get_run(result["run_id"])["status"] == "succeeded"
    assert (
        service.registry.list_audit_events("team-a", "churn")[0]["event_type"]
        == "tracking_mirror_degraded"
    )
