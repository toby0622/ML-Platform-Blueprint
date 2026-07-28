"""Quality gates and safe model deployment transitions."""

from __future__ import annotations

from dataclasses import dataclass

from .domain import (
    CanaryObservation,
    ConflictError,
    DeploymentState,
    GateDecision,
    GateRejectedError,
    NotFoundError,
)
from .registry import Registry


@dataclass(frozen=True, slots=True)
class QualityGatePolicy:
    """Offline thresholds required before a model may receive traffic."""

    minimum_accuracy: float = 0.72
    minimum_f1: float = 0.68
    minimum_roc_auc: float = 0.78
    maximum_brier_score: float = 0.20
    minimum_evaluation_samples: int = 100

    def evaluate(self, metrics: dict[str, float]) -> GateDecision:
        thresholds = {
            "minimum_accuracy": self.minimum_accuracy,
            "minimum_f1": self.minimum_f1,
            "minimum_roc_auc": self.minimum_roc_auc,
            "maximum_brier_score": self.maximum_brier_score,
            "minimum_evaluation_samples": float(self.minimum_evaluation_samples),
        }
        required = (
            "accuracy",
            "f1",
            "roc_auc",
            "brier_score",
            "evaluation_samples",
        )
        missing = [name for name in required if name not in metrics]
        if missing:
            return GateDecision(
                accepted=False,
                checks={f"metric_present:{name}": False for name in missing},
                observed={},
                thresholds=thresholds,
                reasons=(f"missing required metrics: {', '.join(missing)}",),
            )

        observed = {name: float(metrics[name]) for name in required}
        checks = {
            "accuracy": observed["accuracy"] >= self.minimum_accuracy,
            "f1": observed["f1"] >= self.minimum_f1,
            "roc_auc": observed["roc_auc"] >= self.minimum_roc_auc,
            "brier_score": observed["brier_score"] <= self.maximum_brier_score,
            "evaluation_samples": (
                observed["evaluation_samples"] >= self.minimum_evaluation_samples
            ),
        }
        reasons = tuple(
            {
                "accuracy": (
                    f"accuracy {observed['accuracy']:.4f} is below {self.minimum_accuracy:.4f}"
                ),
                "f1": f"f1 {observed['f1']:.4f} is below {self.minimum_f1:.4f}",
                "roc_auc": (
                    f"roc_auc {observed['roc_auc']:.4f} is below {self.minimum_roc_auc:.4f}"
                ),
                "brier_score": (
                    f"brier_score {observed['brier_score']:.4f} exceeds "
                    f"{self.maximum_brier_score:.4f}"
                ),
                "evaluation_samples": (
                    f"evaluation_samples {observed['evaluation_samples']:.0f} is below "
                    f"{self.minimum_evaluation_samples}"
                ),
            }[name]
            for name, passed in checks.items()
            if not passed
        )
        return GateDecision(
            accepted=all(checks.values()),
            checks=checks,
            observed=observed,
            thresholds=thresholds,
            reasons=reasons,
        )


@dataclass(frozen=True, slots=True)
class CanaryGatePolicy:
    """Online SLI guardrails required to complete a canary."""

    maximum_error_rate_increase: float = 0.02
    maximum_latency_ratio: float = 1.25
    minimum_sample_size: int = 100

    def evaluate(self, observation: CanaryObservation) -> GateDecision:
        latency_limit = max(1.0, observation.stable_p95_ms * self.maximum_latency_ratio)
        error_limit = observation.stable_error_rate + self.maximum_error_rate_increase
        checks = {
            "error_rate": observation.canary_error_rate <= error_limit,
            "p95_latency": observation.canary_p95_ms <= latency_limit,
            "sample_size": observation.sample_size >= self.minimum_sample_size,
        }
        reasons: list[str] = []
        if not checks["error_rate"]:
            reasons.append(
                f"canary error rate {observation.canary_error_rate:.4f} exceeds {error_limit:.4f}"
            )
        if not checks["p95_latency"]:
            reasons.append(
                f"canary p95 {observation.canary_p95_ms:.2f}ms exceeds {latency_limit:.2f}ms"
            )
        if not checks["sample_size"]:
            reasons.append(
                f"sample size {observation.sample_size} is below {self.minimum_sample_size}"
            )
        return GateDecision(
            accepted=all(checks.values()),
            checks=checks,
            observed={
                "stable_error_rate": observation.stable_error_rate,
                "canary_error_rate": observation.canary_error_rate,
                "stable_p95_ms": observation.stable_p95_ms,
                "canary_p95_ms": observation.canary_p95_ms,
                "sample_size": float(observation.sample_size),
            },
            thresholds={
                "maximum_error_rate_increase": self.maximum_error_rate_increase,
                "maximum_latency_ratio": self.maximum_latency_ratio,
                "minimum_sample_size": float(self.minimum_sample_size),
            },
            reasons=tuple(reasons),
        )


class PromotionController:
    """Reconcile desired promotion actions into an auditable deployment state."""

    def __init__(
        self,
        registry: Registry,
        quality_policy: QualityGatePolicy | None = None,
        canary_policy: CanaryGatePolicy | None = None,
    ) -> None:
        self.registry = registry
        self.quality_policy = quality_policy or QualityGatePolicy()
        self.canary_policy = canary_policy or CanaryGatePolicy()

    def promote(
        self,
        *,
        tenant: str,
        model_name: str,
        version: int,
        canary_weight: int,
        actor: str,
        reason: str,
    ) -> tuple[DeploymentState, GateDecision]:
        if not 1 <= canary_weight <= 50:
            raise ConflictError("canary_weight must be between 1 and 50")
        record = self.registry.get_version(tenant, model_name, version)
        decision = self.quality_policy.evaluate(record.metrics)
        if not decision.accepted:
            self.registry.record_audit(
                event_type="promotion_rejected",
                tenant=tenant,
                model_name=model_name,
                version=version,
                actor=actor,
                reason=reason,
                payload={"quality_gate": decision.to_dict()},
            )
            raise GateRejectedError(
                f"quality gate rejected {tenant}/{model_name}:{version}",
                decision,
            )

        try:
            current = self.registry.get_deployment(tenant, model_name)
        except NotFoundError:
            state = self.registry.apply_deployment(
                tenant=tenant,
                model_name=model_name,
                stable_version=version,
                canary_version=None,
                canary_weight=0,
                action="initial_model_promoted",
                actor=actor,
                reason=reason,
                payload={"quality_gate": decision.to_dict()},
            )
            return state, decision

        if current.stable_version == version:
            raise ConflictError(f"version {version} is already production")
        if current.canary_version is not None:
            raise ConflictError(f"canary version {current.canary_version} is already active")
        state = self.registry.apply_deployment(
            tenant=tenant,
            model_name=model_name,
            stable_version=current.stable_version,
            canary_version=version,
            canary_weight=canary_weight,
            action="canary_started",
            actor=actor,
            reason=reason,
            payload={"quality_gate": decision.to_dict()},
        )
        return state, decision

    def finalize_canary(
        self,
        *,
        tenant: str,
        model_name: str,
        observation: CanaryObservation,
        actor: str,
        reason: str,
    ) -> tuple[DeploymentState, GateDecision]:
        current = self.registry.get_deployment(tenant, model_name)
        if current.canary_version is None:
            raise ConflictError("there is no active canary to finalize")
        decision = self.canary_policy.evaluate(observation)
        if not decision.accepted:
            self.registry.apply_deployment(
                tenant=tenant,
                model_name=model_name,
                stable_version=current.stable_version,
                canary_version=None,
                canary_weight=0,
                action="canary_auto_rollback",
                actor=actor,
                reason=reason,
                payload={
                    "canary_version": current.canary_version,
                    "online_gate": decision.to_dict(),
                },
            )
            raise GateRejectedError(
                f"online canary gate rejected {tenant}/{model_name}:"
                f"{current.canary_version}; rollback completed",
                decision,
            )

        state = self.registry.apply_deployment(
            tenant=tenant,
            model_name=model_name,
            stable_version=current.canary_version,
            canary_version=None,
            canary_weight=0,
            action="canary_finalized",
            actor=actor,
            reason=reason,
            payload={
                "previous_stable_version": current.stable_version,
                "online_gate": decision.to_dict(),
            },
        )
        return state, decision

    def rollback(
        self,
        *,
        tenant: str,
        model_name: str,
        actor: str,
        reason: str,
        target_version: int | None = None,
    ) -> DeploymentState:
        current = self.registry.get_deployment(tenant, model_name)
        if target_version is not None:
            self.registry.get_version(tenant, model_name, target_version)
            if target_version == current.stable_version and current.canary_version is None:
                raise ConflictError("target version is already the sole stable version")
            return self.registry.apply_deployment(
                tenant=tenant,
                model_name=model_name,
                stable_version=target_version,
                canary_version=None,
                canary_weight=0,
                action="manual_rollback",
                actor=actor,
                reason=reason,
                payload={
                    "previous_stable_version": current.stable_version,
                    "discarded_canary_version": current.canary_version,
                },
            )

        if current.canary_version is None:
            raise ConflictError(
                "there is no active canary; provide target_version for a stable rollback"
            )
        return self.registry.apply_deployment(
            tenant=tenant,
            model_name=model_name,
            stable_version=current.stable_version,
            canary_version=None,
            canary_weight=0,
            action="canary_manual_rollback",
            actor=actor,
            reason=reason,
            payload={"discarded_canary_version": current.canary_version},
        )
