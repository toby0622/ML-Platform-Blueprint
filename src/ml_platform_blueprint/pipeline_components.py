"""Artifact-oriented component entrypoints used by Kubeflow Pipelines."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .data import Dataset, generate_churn_dataset, stratified_split, validate_dataset
from .metrics import evaluate_binary_classifier
from .model import (
    ModelArtifact,
    predict_probabilities,
    train_logistic_regression,
)
from .promotion import QualityGatePolicy
from .utils import atomic_write_text, canonical_json, validate_resource_name


def validate_component(args: argparse.Namespace) -> dict[str, Any]:
    dataset = generate_churn_dataset(samples=args.samples, seed=args.data_seed)
    validate_dataset(dataset)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        features=dataset.features,
        labels=dataset.labels,
        feature_names=np.asarray(dataset.feature_names),
    )
    metadata = dataset.metadata | {"sha256": dataset.checksum}
    atomic_write_text(Path(args.metadata), canonical_json(metadata) + "\n")
    return metadata


def _load_dataset(path: Path, metadata_path: Path) -> Dataset:
    with np.load(path, allow_pickle=False) as payload:
        features = np.asarray(payload["features"], dtype=np.float64)
        labels = np.asarray(payload["labels"], dtype=np.int64)
        feature_names = tuple(str(value) for value in payload["feature_names"])
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    dataset = Dataset(
        features=features,
        labels=labels,
        feature_names=feature_names,
        checksum=str(metadata["sha256"]),
        metadata=metadata,
    )
    validate_dataset(dataset)
    return dataset


def train_component(args: argparse.Namespace) -> dict[str, Any]:
    dataset = _load_dataset(Path(args.dataset), Path(args.dataset_metadata))
    train_x, test_x, train_y, test_y = stratified_split(
        dataset,
        test_fraction=args.test_fraction,
        seed=args.split_seed,
    )
    artifact = train_logistic_regression(
        train_x,
        train_y,
        dataset.feature_names,
        learning_rate=args.learning_rate,
        epochs=args.epochs,
        l2=args.l2,
        decision_threshold=args.decision_threshold,
    )
    atomic_write_text(Path(args.model), artifact.to_json())
    evaluation_path = Path(args.evaluation_data)
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(evaluation_path, features=test_x, labels=test_y)
    parameters = {
        "samples": int(dataset.metadata["samples"]),
        "data_seed": int(dataset.metadata["seed"]),
        "split_seed": args.split_seed,
        "test_fraction": args.test_fraction,
        "learning_rate": args.learning_rate,
        "epochs": args.epochs,
        "l2": args.l2,
        "decision_threshold": args.decision_threshold,
    }
    atomic_write_text(Path(args.parameters), canonical_json(parameters) + "\n")
    return parameters


def evaluate_component(args: argparse.Namespace) -> dict[str, Any]:
    artifact = ModelArtifact.from_dict(json.loads(Path(args.model).read_text(encoding="utf-8")))
    with np.load(Path(args.evaluation_data), allow_pickle=False) as payload:
        features = np.asarray(payload["features"], dtype=np.float64)
        labels = np.asarray(payload["labels"], dtype=np.int64)
    probabilities = predict_probabilities(artifact, features)
    metrics = evaluate_binary_classifier(
        labels, probabilities, threshold=artifact.decision_threshold
    )
    decision = QualityGatePolicy().evaluate(metrics)
    result = {"metrics": metrics, "quality_gate": decision.to_dict()}
    atomic_write_text(Path(args.metrics), canonical_json(result) + "\n")
    if args.enforce_gate and not decision.accepted:
        raise RuntimeError("; ".join(decision.reasons))
    return result


def register_component(args: argparse.Namespace) -> dict[str, Any]:
    """Register arbitrary model files and lineage in an MLflow model registry."""

    try:
        import mlflow
        from mlflow import MlflowClient
        from mlflow.exceptions import MlflowException
    except ImportError as error:
        raise RuntimeError("register component requires the mlflow extra") from error

    validate_resource_name(args.tenant, "tenant")
    validate_resource_name(args.model_name, "model_name")
    registered_model_name = f"{args.tenant}--{args.model_name}"
    parameters = json.loads(Path(args.parameters).read_text(encoding="utf-8"))
    evaluation = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    metrics = evaluation["metrics"]
    gate = evaluation["quality_gate"]
    if not gate["accepted"]:
        raise RuntimeError(f"quality gate rejected model: {gate['reasons']}")

    mlflow.set_tracking_uri(args.tracking_uri)
    mlflow.set_experiment(args.experiment)
    with mlflow.start_run(
        run_name=args.pipeline_run_id,
        tags={
            "platform.tenant": args.tenant,
            "platform.model_name": args.model_name,
            "platform.pipeline_run_id": args.pipeline_run_id,
            "platform.code_revision": args.code_revision,
            "platform.dataset_sha256": json.loads(
                Path(args.dataset_metadata).read_text(encoding="utf-8")
            )["sha256"],
        },
    ) as run:
        mlflow.log_params(parameters)
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(args.model, artifact_path="model")
        mlflow.log_artifact(args.metrics, artifact_path="evaluation")
        source = f"{run.info.artifact_uri}/model"
        client = MlflowClient()
        try:
            client.create_registered_model(registered_model_name)
        except MlflowException as error:
            if error.error_code != "RESOURCE_ALREADY_EXISTS":
                raise
        version = client.create_model_version(
            name=registered_model_name,
            source=source,
            run_id=run.info.run_id,
            tags={
                "tenant": args.tenant,
                "code_revision": args.code_revision,
                "dataset_sha256": json.loads(
                    Path(args.dataset_metadata).read_text(encoding="utf-8")
                )["sha256"],
                "pipeline_run_id": args.pipeline_run_id,
                "quality_gate": "passed",
            },
        )
    result = {
        "run_id": run.info.run_id,
        "model_name": args.model_name,
        "registered_model_name": registered_model_name,
        "model_version": version.version,
        "source": source,
    }
    atomic_write_text(Path(args.registration), canonical_json(result) + "\n")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ML pipeline component entrypoints")
    components = parser.add_subparsers(dest="component", required=True)

    validate = components.add_parser("validate")
    validate.add_argument("--samples", type=int, required=True)
    validate.add_argument("--data-seed", type=int, required=True)
    validate.add_argument("--output", required=True)
    validate.add_argument("--metadata", required=True)

    train = components.add_parser("train")
    train.add_argument("--dataset", required=True)
    train.add_argument("--dataset-metadata", required=True)
    train.add_argument("--model", required=True)
    train.add_argument("--evaluation-data", required=True)
    train.add_argument("--parameters", required=True)
    train.add_argument("--split-seed", type=int, required=True)
    train.add_argument("--test-fraction", type=float, required=True)
    train.add_argument("--learning-rate", type=float, required=True)
    train.add_argument("--epochs", type=int, required=True)
    train.add_argument("--l2", type=float, required=True)
    train.add_argument("--decision-threshold", type=float, required=True)

    evaluate = components.add_parser("evaluate")
    evaluate.add_argument("--model", required=True)
    evaluate.add_argument("--evaluation-data", required=True)
    evaluate.add_argument("--metrics", required=True)
    evaluate.add_argument("--enforce-gate", action="store_true")

    register = components.add_parser("register")
    register.add_argument("--model", required=True)
    register.add_argument("--parameters", required=True)
    register.add_argument("--metrics", required=True)
    register.add_argument("--registration", required=True)
    register.add_argument("--tracking-uri", required=True)
    register.add_argument("--experiment", required=True)
    register.add_argument("--tenant", required=True)
    register.add_argument("--model-name", required=True)
    register.add_argument("--pipeline-run-id", required=True)
    register.add_argument("--code-revision", required=True)
    register.add_argument("--dataset-metadata", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "validate": validate_component,
        "train": train_component,
        "evaluate": evaluate_component,
        "register": register_component,
    }
    try:
        result = handlers[args.component](args)
        print(canonical_json(result))
        return 0
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
