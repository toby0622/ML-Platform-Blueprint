"""KServe-compatible HTTP runtime for the reference model artifact."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from .domain import ValidationError
from .model import ModelArtifact, predict_probabilities
from .utils import sha256_bytes


class V1Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instances: list[dict[str, float] | list[float]] = Field(min_length=1)


class V2Input(BaseModel):
    name: str
    shape: list[int]
    datatype: str
    data: list[Any]


class V2Request(BaseModel):
    id: str | None = None
    inputs: list[V2Input] = Field(min_length=1)


class RuntimeMetrics:
    def __init__(self) -> None:
        self.requests = 0
        self.errors = 0
        self.duration_sum = 0.0
        self._lock = threading.Lock()

    def record(self, duration_seconds: float, *, error: bool) -> None:
        with self._lock:
            self.requests += 1
            self.errors += int(error)
            self.duration_sum += duration_seconds

    def render(self, model_name: str, model_version: str) -> str:
        labels = f'model="{model_name}",version="{model_version}"'
        with self._lock:
            requests = self.requests
            errors = self.errors
            duration_sum = self.duration_sum
        return "\n".join(
            (
                "# HELP model_server_requests_total Inference requests.",
                "# TYPE model_server_requests_total counter",
                f"model_server_requests_total{{{labels}}} {requests}",
                "# HELP model_server_errors_total Failed inference requests.",
                "# TYPE model_server_errors_total counter",
                f"model_server_errors_total{{{labels}}} {errors}",
                "# HELP model_server_duration_seconds Inference request duration.",
                "# TYPE model_server_duration_seconds summary",
                f"model_server_duration_seconds_sum{{{labels}}} {duration_sum:.9f}",
                f"model_server_duration_seconds_count{{{labels}}} {requests}",
                "",
            )
        )


def _load_artifact(path: Path, expected_sha256: str | None) -> ModelArtifact:
    try:
        content = path.read_bytes()
    except FileNotFoundError as error:
        raise RuntimeError(f"model artifact does not exist: {path}") from error
    observed_sha256 = sha256_bytes(content)
    if expected_sha256 and observed_sha256 != expected_sha256:
        raise RuntimeError(
            f"model artifact SHA-256 mismatch: expected {expected_sha256}, "
            f"observed {observed_sha256}"
        )
    try:
        return ModelArtifact.from_dict(json.loads(content))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid model artifact at {path}: {error}") from error


def _rows_from_v1(
    artifact: ModelArtifact, instances: list[dict[str, float] | list[float]]
) -> np.ndarray[Any, np.dtype[np.float64]]:
    rows: list[list[float]] = []
    expected = set(artifact.feature_names)
    for index, instance in enumerate(instances):
        if isinstance(instance, dict):
            provided = set(instance)
            if provided != expected:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": f"instance {index} has a schema mismatch",
                        "missing": sorted(expected - provided),
                        "unexpected": sorted(provided - expected),
                    },
                )
            rows.append([float(instance[name]) for name in artifact.feature_names])
        else:
            if len(instance) != len(artifact.feature_names):
                raise HTTPException(
                    status_code=400,
                    detail=f"instance {index} must have {len(artifact.feature_names)} values",
                )
            rows.append([float(value) for value in instance])
    return np.asarray(rows, dtype=np.float64)


def _rows_from_v2(
    artifact: ModelArtifact, inputs: list[V2Input]
) -> np.ndarray[Any, np.dtype[np.float64]]:
    feature_input = next((item for item in inputs if item.name in {"features", "input-0"}), None)
    if feature_input is None:
        raise HTTPException(status_code=400, detail="V2 request requires an input named 'features'")
    if feature_input.datatype not in {"FP32", "FP64"}:
        raise HTTPException(status_code=400, detail="features datatype must be FP32 or FP64")
    if len(feature_input.shape) != 2 or feature_input.shape[1] != len(artifact.feature_names):
        raise HTTPException(
            status_code=400,
            detail=(f"features shape must be [batch, {len(artifact.feature_names)}]"),
        )
    matrix = np.asarray(feature_input.data, dtype=np.float64)
    try:
        return matrix.reshape(feature_input.shape)
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail="features data does not match its shape"
        ) from error


def create_model_app(
    *,
    artifact_path: Path,
    model_name: str = "churn-classifier",
    model_version: str = "unknown",
    expected_sha256: str | None = None,
) -> FastAPI:
    artifact = _load_artifact(artifact_path, expected_sha256)
    metrics = RuntimeMetrics()
    application = FastAPI(
        title=f"{model_name} model server",
        version=model_version,
        description="KServe V1/V2-compatible reference model runtime.",
    )

    def infer(matrix: np.ndarray[Any, np.dtype[np.float64]]) -> tuple[list[int], list[float]]:
        started = time.perf_counter()
        failed = False
        try:
            probabilities = predict_probabilities(artifact, matrix)
            labels = [int(value >= artifact.decision_threshold) for value in probabilities]
            return labels, [float(value) for value in probabilities]
        except ValidationError as error:
            failed = True
            raise HTTPException(status_code=400, detail=str(error)) from error
        except BaseException:
            failed = True
            raise
        finally:
            metrics.record(time.perf_counter() - started, error=failed)

    @application.get("/healthz")
    @application.get("/v2/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz")
    @application.get("/v2/health/ready")
    def ready() -> dict[str, str]:
        return {"status": "ready"}

    @application.get("/v1/models/{requested_model}")
    @application.get("/v2/models/{requested_model}")
    @application.get("/v2/models/{requested_model}/ready")
    def model_ready(requested_model: str) -> dict[str, Any]:
        if requested_model != model_name:
            raise HTTPException(status_code=404, detail="model not found")
        return {
            "name": model_name,
            "version": model_version,
            "ready": True,
            "feature_names": list(artifact.feature_names),
        }

    @application.post("/v1/models/{requested_model}:predict")
    def predict_v1(requested_model: str, body: V1Request) -> dict[str, Any]:
        if requested_model != model_name:
            raise HTTPException(status_code=404, detail="model not found")
        labels, probabilities = infer(_rows_from_v1(artifact, body.instances))
        return {
            "model_name": model_name,
            "model_version": model_version,
            "predictions": [
                {"label": label, "probability": probability}
                for label, probability in zip(labels, probabilities, strict=True)
            ],
        }

    @application.post("/v2/models/{requested_model}/infer")
    def predict_v2(requested_model: str, body: V2Request, request: Request) -> dict[str, Any]:
        if requested_model != model_name:
            raise HTTPException(status_code=404, detail="model not found")
        labels, probabilities = infer(_rows_from_v2(artifact, body.inputs))
        return {
            "id": body.id or request.headers.get("X-Request-Id"),
            "model_name": model_name,
            "model_version": model_version,
            "outputs": [
                {
                    "name": "probabilities",
                    "shape": [len(probabilities), 1],
                    "datatype": "FP64",
                    "data": probabilities,
                },
                {
                    "name": "labels",
                    "shape": [len(labels), 1],
                    "datatype": "INT64",
                    "data": labels,
                },
            ],
        }

    @application.get("/metrics", response_class=PlainTextResponse)
    def prometheus_metrics() -> PlainTextResponse:
        return PlainTextResponse(
            metrics.render(model_name, model_version),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return application


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve a registered model artifact.")
    parser.add_argument(
        "--artifact",
        default=os.getenv("MODEL_ARTIFACT_PATH", "/mnt/models/model.json"),
    )
    parser.add_argument("--model-name", default=os.getenv("MODEL_NAME", "churn-classifier"))
    parser.add_argument("--model-version", default=os.getenv("MODEL_VERSION", "unknown"))
    parser.add_argument("--artifact-sha256", default=os.getenv("MODEL_ARTIFACT_SHA256"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        app = create_model_app(
            artifact_path=Path(args.artifact),
            model_name=args.model_name,
            model_version=args.model_version,
            expected_sha256=args.artifact_sha256,
        )
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
