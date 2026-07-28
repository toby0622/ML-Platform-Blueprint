"""Domain types used at the platform boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class PlatformError(RuntimeError):
    """Base class for expected platform errors."""

    code = "platform_error"


class NotFoundError(PlatformError):
    code = "not_found"


class ConflictError(PlatformError):
    code = "conflict"


class ValidationError(PlatformError):
    code = "validation_failed"


class TenantAccessError(PlatformError):
    code = "tenant_access_denied"


class GateRejectedError(PlatformError):
    code = "quality_gate_rejected"

    def __init__(self, message: str, decision: GateDecision) -> None:
        super().__init__(message)
        self.decision = decision


@dataclass(frozen=True, slots=True)
class GateDecision:
    accepted: bool
    checks: dict[str, bool]
    observed: dict[str, float]
    thresholds: dict[str, float]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reasons"] = list(self.reasons)
        return value


@dataclass(frozen=True, slots=True)
class ModelVersion:
    tenant: str
    model_name: str
    version: int
    run_id: str
    stage: str
    artifact_path: str
    artifact_sha256: str
    dataset_sha256: str
    code_revision: str
    parameters: dict[str, Any]
    metrics: dict[str, float]
    model_card_path: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DeploymentState:
    tenant: str
    model_name: str
    stable_version: int
    canary_version: int | None
    canary_weight: int
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CanaryObservation:
    stable_error_rate: float
    canary_error_rate: float
    stable_p95_ms: float
    canary_p95_ms: float
    sample_size: int

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)
