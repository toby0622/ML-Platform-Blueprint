"""A small, deterministic logistic-regression runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .domain import ValidationError
from .utils import canonical_json


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    schema_version: str
    algorithm: str
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    decision_threshold: float

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["feature_names"] = list(self.feature_names)
        result["means"] = list(self.means)
        result["scales"] = list(self.scales)
        result["coefficients"] = list(self.coefficients)
        return result

    def to_json(self) -> str:
        return canonical_json(self.to_dict()) + "\n"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ModelArtifact:
        if value.get("schema_version") != "1":
            raise ValidationError("unsupported model artifact schema")
        return cls(
            schema_version="1",
            algorithm=str(value["algorithm"]),
            feature_names=tuple(str(item) for item in value["feature_names"]),
            means=tuple(float(item) for item in value["means"]),
            scales=tuple(float(item) for item in value["scales"]),
            coefficients=tuple(float(item) for item in value["coefficients"]),
            intercept=float(value["intercept"]),
            decision_threshold=float(value["decision_threshold"]),
        )


def _sigmoid(values: NDArray[np.float64]) -> NDArray[np.float64]:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -35, 35)))


def train_logistic_regression(
    features: NDArray[np.float64],
    labels: NDArray[np.int64],
    feature_names: tuple[str, ...],
    *,
    learning_rate: float = 0.12,
    epochs: int = 700,
    l2: float = 0.01,
    decision_threshold: float = 0.5,
) -> ModelArtifact:
    """Fit a standardized logistic model using deterministic batch descent."""

    if features.ndim != 2 or labels.ndim != 1:
        raise ValidationError("training inputs have invalid dimensions")
    if features.shape[0] != labels.shape[0]:
        raise ValidationError("training feature and label counts differ")
    if features.shape[1] != len(feature_names):
        raise ValidationError("training feature schema does not match the data")
    if not 0 < learning_rate <= 1:
        raise ValidationError("learning_rate must be in (0, 1]")
    if not 10 <= epochs <= 20_000:
        raise ValidationError("epochs must be between 10 and 20000")
    if not 0 <= l2 <= 10:
        raise ValidationError("l2 must be between 0 and 10")
    if not 0 < decision_threshold < 1:
        raise ValidationError("decision_threshold must be in (0, 1)")

    means = np.mean(features, axis=0)
    scales = np.std(features, axis=0)
    scales = np.where(scales < 1e-12, 1.0, scales)
    standardized = (features - means) / scales
    weights = np.zeros(features.shape[1], dtype=np.float64)
    intercept = 0.0

    for _ in range(epochs):
        probabilities = _sigmoid(standardized @ weights + intercept)
        error = probabilities - labels
        gradient = (standardized.T @ error) / len(labels) + l2 * weights
        intercept_gradient = float(np.mean(error))
        weights -= learning_rate * gradient
        intercept -= learning_rate * intercept_gradient

    return ModelArtifact(
        schema_version="1",
        algorithm="logistic-regression-batch-gradient-descent",
        feature_names=feature_names,
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in weights),
        intercept=float(intercept),
        decision_threshold=decision_threshold,
    )


def predict_probabilities(
    artifact: ModelArtifact,
    features: NDArray[np.float64],
) -> NDArray[np.float64]:
    if features.ndim != 2 or features.shape[1] != len(artifact.feature_names):
        raise ValidationError("prediction input does not match the model schema")
    if not np.all(np.isfinite(features)):
        raise ValidationError("prediction input contains NaN or infinite values")
    means = np.asarray(artifact.means, dtype=np.float64)
    scales = np.asarray(artifact.scales, dtype=np.float64)
    weights = np.asarray(artifact.coefficients, dtype=np.float64)
    standardized = (features - means) / scales
    return _sigmoid(standardized @ weights + artifact.intercept)


def predict_labels(
    artifact: ModelArtifact,
    features: NDArray[np.float64],
) -> NDArray[np.int64]:
    probabilities = predict_probabilities(artifact, features)
    return (probabilities >= artifact.decision_threshold).astype(np.int64)
