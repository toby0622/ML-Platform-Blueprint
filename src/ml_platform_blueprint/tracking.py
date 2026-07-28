"""Tracking adapter: always-local evidence with optional MLflow mirroring."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol, cast

from .config import Settings
from .utils import atomic_write_text, canonical_json, utc_now


class Tracker(Protocol):
    def start(
        self,
        *,
        run_id: str,
        tenant: str,
        model_name: str,
        tags: dict[str, str],
    ) -> None: ...

    def log_parameters(self, run_id: str, parameters: dict[str, Any]) -> None: ...

    def log_metrics(self, run_id: str, metrics: dict[str, float]) -> None: ...

    def finish(self, run_id: str, status: str) -> None: ...


class LocalTracker:
    """Write stable tracking snapshots even when MLflow is not available."""

    def __init__(self, state_dir: Path) -> None:
        self.root = state_dir.resolve() / "tracking"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read(self, run_id: str) -> dict[str, Any]:
        path = self.root / f"{run_id}.json"
        if not path.exists():
            return {"run_id": run_id}
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))

    def _update(self, run_id: str, values: dict[str, Any]) -> None:
        with self._lock:
            snapshot = self._read(run_id)
            snapshot.update(values)
            atomic_write_text(self.root / f"{run_id}.json", canonical_json(snapshot) + "\n")

    def start(
        self,
        *,
        run_id: str,
        tenant: str,
        model_name: str,
        tags: dict[str, str],
    ) -> None:
        self._update(
            run_id,
            {
                "tenant": tenant,
                "model_name": model_name,
                "tags": tags,
                "status": "RUNNING",
                "started_at": utc_now(),
            },
        )

    def log_parameters(self, run_id: str, parameters: dict[str, Any]) -> None:
        self._update(run_id, {"parameters": parameters})

    def log_metrics(self, run_id: str, metrics: dict[str, float]) -> None:
        self._update(run_id, {"metrics": metrics})

    def finish(self, run_id: str, status: str) -> None:
        self._update(run_id, {"status": status, "ended_at": utc_now()})


class MlflowMirrorTracker:
    """Mirror local tracking events to an MLflow server when configured."""

    def __init__(self, local: LocalTracker, settings: Settings) -> None:
        try:
            import mlflow
        except ImportError as error:
            raise RuntimeError(
                "MLFLOW_TRACKING_URI is set but the mlflow extra is not installed; "
                "run `pip install -e .[mlflow]`"
            ) from error
        self.local = local
        self.client = mlflow.MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
        experiment = self.client.get_experiment_by_name(settings.mlflow_experiment)
        self.experiment_id = (
            experiment.experiment_id
            if experiment is not None
            else self.client.create_experiment(settings.mlflow_experiment)
        )
        self._active: dict[str, str] = {}
        self._lock = threading.Lock()

    def start(
        self,
        *,
        run_id: str,
        tenant: str,
        model_name: str,
        tags: dict[str, str],
    ) -> None:
        self.local.start(
            run_id=run_id,
            tenant=tenant,
            model_name=model_name,
            tags=tags,
        )
        run = self.client.create_run(
            experiment_id=self.experiment_id,
            tags={
                **tags,
                "mlflow.runName": run_id,
                "platform.run_id": run_id,
                "platform.tenant": tenant,
                "platform.model_name": model_name,
            },
        )
        with self._lock:
            self._active[run_id] = str(run.info.run_id)

    def _remote_run_id(self, run_id: str) -> str:
        with self._lock:
            remote_run_id = self._active.get(run_id)
        if remote_run_id is None:
            raise RuntimeError(f"tracking run {run_id!r} is not active")
        return remote_run_id

    def log_parameters(self, run_id: str, parameters: dict[str, Any]) -> None:
        self.local.log_parameters(run_id, parameters)
        remote_run_id = self._remote_run_id(run_id)
        for key, value in parameters.items():
            self.client.log_param(remote_run_id, key, value)

    def log_metrics(self, run_id: str, metrics: dict[str, float]) -> None:
        self.local.log_metrics(run_id, metrics)
        remote_run_id = self._remote_run_id(run_id)
        for key, value in metrics.items():
            self.client.log_metric(remote_run_id, key, value)

    def finish(self, run_id: str, status: str) -> None:
        self.local.finish(run_id, status)
        with self._lock:
            remote_run_id = self._active.pop(run_id, None)
        if remote_run_id is not None:
            self.client.set_terminated(remote_run_id, status=status)


def create_tracker(settings: Settings) -> Tracker:
    local = LocalTracker(settings.state_dir)
    if settings.mlflow_tracking_uri:
        return MlflowMirrorTracker(local, settings)
    return local
