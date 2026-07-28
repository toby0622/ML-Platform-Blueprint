"""Application service composing training, registry, promotion, and serving."""

from __future__ import annotations

import hashlib
import time
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from .config import Settings
from .data import generate_churn_dataset, stratified_split
from .domain import (
    CanaryObservation,
    GateRejectedError,
    TenantAccessError,
    ValidationError,
)
from .metrics import evaluate_binary_classifier
from .model import predict_probabilities, train_logistic_regression
from .promotion import PromotionController
from .registry import Registry
from .telemetry import Telemetry
from .tracking import Tracker, create_tracker
from .utils import validate_resource_name


@dataclass(frozen=True, slots=True)
class TrainingParameters:
    samples: int = 800
    data_seed: int = 42
    split_seed: int = 42
    test_fraction: float = 0.2
    learning_rate: float = 0.12
    epochs: int = 700
    l2: float = 0.01
    decision_threshold: float = 0.5

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


class PlatformService:
    """Public use cases for the HTTP API, CLI, and pipeline components."""

    def __init__(
        self,
        settings: Settings,
        *,
        registry: Registry | None = None,
        tracker: Tracker | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry or Registry(settings.state_dir)
        self.tracker = tracker or create_tracker(settings)
        self.telemetry = telemetry or Telemetry()
        self.promotions = PromotionController(self.registry)

    def authorize_tenant(self, tenant: str) -> None:
        validate_resource_name(tenant, "tenant")
        if tenant not in self.settings.allowed_tenants:
            raise TenantAccessError(f"tenant {tenant!r} is not allowed")

    def _finish_tracking(
        self,
        *,
        run_id: str,
        status: str,
        tenant: str,
        model_name: str,
        version: int | None,
    ) -> None:
        """Finish the tracking mirror without invalidating durable registry state."""

        try:
            self.tracker.finish(run_id, status)
        except Exception as error:
            # Preserve the original lifecycle result even if both best-effort
            # evidence sinks are unavailable.
            with suppress(Exception):
                self.registry.record_audit(
                    event_type="tracking_mirror_degraded",
                    tenant=tenant,
                    model_name=model_name,
                    version=version,
                    actor="platform-service",
                    reason="tracking mirror could not record terminal status",
                    payload={"run_id": run_id, "error_type": type(error).__name__},
                )

    def train_and_register(
        self,
        *,
        tenant: str,
        model_name: str,
        parameters: TrainingParameters | None = None,
    ) -> dict[str, Any]:
        self.authorize_tenant(tenant)
        validate_resource_name(model_name, "model_name")
        selected = parameters or TrainingParameters()
        parameter_values = selected.to_dict()
        dataset = generate_churn_dataset(samples=selected.samples, seed=selected.data_seed)
        run_id = uuid.uuid4().hex
        self.registry.create_run(
            run_id=run_id,
            tenant=tenant,
            model_name=model_name,
            code_revision=self.settings.code_revision,
            dataset_sha256=dataset.checksum,
            parameters=parameter_values,
        )
        try:
            self.tracker.start(
                run_id=run_id,
                tenant=tenant,
                model_name=model_name,
                tags={
                    "code_revision": self.settings.code_revision,
                    "dataset_sha256": dataset.checksum,
                    "environment": self.settings.environment,
                    "pipeline": "validate-train-evaluate-register",
                },
            )
            self.tracker.log_parameters(run_id, parameter_values)
            train_features, test_features, train_labels, test_labels = stratified_split(
                dataset,
                test_fraction=selected.test_fraction,
                seed=selected.split_seed,
            )
            artifact = train_logistic_regression(
                train_features,
                train_labels,
                dataset.feature_names,
                learning_rate=selected.learning_rate,
                epochs=selected.epochs,
                l2=selected.l2,
                decision_threshold=selected.decision_threshold,
            )
            probabilities = predict_probabilities(artifact, test_features)
            metrics = evaluate_binary_classifier(
                test_labels,
                probabilities,
                threshold=selected.decision_threshold,
            )
            metrics["training_samples"] = float(len(train_labels))
            metrics["dataset_positive_rate"] = float(dataset.metadata["positive_rate"])
            self.tracker.log_metrics(run_id, metrics)
            record = self.registry.register_model(
                tenant=tenant,
                model_name=model_name,
                run_id=run_id,
                artifact=artifact,
                dataset_sha256=dataset.checksum,
                code_revision=self.settings.code_revision,
                parameters=parameter_values,
                metrics=metrics,
            )
            self.registry.complete_run(run_id, metrics)
            self._finish_tracking(
                run_id=run_id,
                status="FINISHED",
                tenant=tenant,
                model_name=model_name,
                version=record.version,
            )
            self.telemetry.record_training(tenant, model_name, "succeeded")
            return {
                "run_id": run_id,
                "model_version": record.to_dict(),
                "dataset": dataset.metadata | {"sha256": dataset.checksum},
            }
        except BaseException as error:
            self.registry.fail_run(run_id, f"{type(error).__name__}: {error}")
            self._finish_tracking(
                run_id=run_id,
                status="FAILED",
                tenant=tenant,
                model_name=model_name,
                version=None,
            )
            self.telemetry.record_training(tenant, model_name, "failed")
            raise

    def promote(
        self,
        *,
        tenant: str,
        model_name: str,
        version: int,
        canary_weight: int,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        self.authorize_tenant(tenant)
        try:
            state, decision = self.promotions.promote(
                tenant=tenant,
                model_name=model_name,
                version=version,
                canary_weight=canary_weight,
                actor=actor,
                reason=reason,
            )
        except GateRejectedError:
            self.telemetry.record_promotion(tenant, model_name, "rejected")
            raise
        self.telemetry.record_promotion(tenant, model_name, "accepted")
        return {
            "deployment": state.to_dict(),
            "quality_gate": decision.to_dict(),
        }

    def finalize_canary(
        self,
        *,
        tenant: str,
        model_name: str,
        observation: CanaryObservation,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        self.authorize_tenant(tenant)
        try:
            state, decision = self.promotions.finalize_canary(
                tenant=tenant,
                model_name=model_name,
                observation=observation,
                actor=actor,
                reason=reason,
            )
        except GateRejectedError:
            self.telemetry.record_promotion(tenant, model_name, "canary_rolled_back")
            raise
        self.telemetry.record_promotion(tenant, model_name, "canary_finalized")
        return {
            "deployment": state.to_dict(),
            "online_gate": decision.to_dict(),
        }

    def rollback(
        self,
        *,
        tenant: str,
        model_name: str,
        actor: str,
        reason: str,
        target_version: int | None = None,
    ) -> dict[str, Any]:
        self.authorize_tenant(tenant)
        state = self.promotions.rollback(
            tenant=tenant,
            model_name=model_name,
            actor=actor,
            reason=reason,
            target_version=target_version,
        )
        self.telemetry.record_promotion(tenant, model_name, "rollback")
        return {"deployment": state.to_dict()}

    @staticmethod
    def _choose_route(
        request_id: str, stable_version: int, canary_version: int | None, weight: int
    ) -> tuple[int, str]:
        if canary_version is None or weight == 0:
            return stable_version, "stable"
        bucket = int(hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:8], 16)
        if bucket % 100 < weight:
            return canary_version, "canary"
        return stable_version, "stable"

    def predict(
        self,
        *,
        tenant: str,
        model_name: str,
        instances: list[dict[str, float]],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        self.authorize_tenant(tenant)
        if not instances:
            raise ValidationError("instances must contain at least one row")
        if len(instances) > 1000:
            raise ValidationError("a prediction request may contain at most 1000 rows")
        if request_id is not None and (not request_id.strip() or len(request_id) > 128):
            raise ValidationError("request_id must contain between 1 and 128 characters")
        deployment = self.registry.get_deployment(tenant, model_name)
        selected_request_id = request_id or uuid.uuid4().hex
        version, route = self._choose_route(
            selected_request_id,
            deployment.stable_version,
            deployment.canary_version,
            deployment.canary_weight,
        )
        started = time.perf_counter()
        outcome = "success"
        try:
            artifact = self.registry.load_artifact(tenant, model_name, version)
            expected = set(artifact.feature_names)
            rows: list[list[float]] = []
            for index, instance in enumerate(instances):
                provided = set(instance)
                missing = sorted(expected - provided)
                unexpected = sorted(provided - expected)
                if missing or unexpected:
                    raise ValidationError(
                        f"instance {index} has schema mismatch; "
                        f"missing={missing}, unexpected={unexpected}"
                    )
                try:
                    rows.append([float(instance[name]) for name in artifact.feature_names])
                except (TypeError, ValueError) as error:
                    raise ValidationError(
                        f"instance {index} contains a non-numeric feature"
                    ) from error
            matrix = np.asarray(rows, dtype=np.float64)
            probabilities = predict_probabilities(artifact, matrix)
            predictions = [
                {
                    "label": int(value >= artifact.decision_threshold),
                    "probability": float(value),
                }
                for value in probabilities
            ]
            return {
                "request_id": selected_request_id,
                "tenant": tenant,
                "model_name": model_name,
                "model_version": version,
                "route": route,
                "predictions": predictions,
            }
        except BaseException:
            outcome = "error"
            raise
        finally:
            self.telemetry.record_prediction(
                tenant,
                model_name,
                version,
                route,
                outcome,
                time.perf_counter() - started,
            )
