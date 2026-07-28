"""Deterministic synthetic churn data and schema validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .domain import ValidationError
from .utils import canonical_json, sha256_bytes

FEATURE_NAMES = (
    "tenure_months",
    "monthly_spend",
    "support_tickets",
    "usage_score",
    "payment_failures",
    "contract_months",
)


@dataclass(frozen=True, slots=True)
class Dataset:
    features: NDArray[np.float64]
    labels: NDArray[np.int64]
    feature_names: tuple[str, ...]
    checksum: str
    metadata: dict[str, Any]


def _dataset_checksum(
    features: NDArray[np.float64],
    labels: NDArray[np.int64],
    feature_names: tuple[str, ...],
) -> str:
    payload = b"ml-platform-dataset-v1\0"
    payload += canonical_json(feature_names).encode("utf-8")
    payload += np.ascontiguousarray(features, dtype="<f8").tobytes()
    payload += np.ascontiguousarray(labels, dtype="<i8").tobytes()
    return sha256_bytes(payload)


def generate_churn_dataset(samples: int = 800, seed: int = 42) -> Dataset:
    """Generate a useful but dependency-light binary classification dataset.

    The generator is deterministic for a given sample count and seed. It avoids
    external downloads so the complete training run can be reproduced offline.
    """

    if samples < 100:
        raise ValidationError("samples must be at least 100")
    if samples > 100_000:
        raise ValidationError("samples must not exceed 100000")

    rng = np.random.default_rng(seed)
    tenure = rng.uniform(0, 72, samples)
    monthly_spend = np.clip(rng.normal(78, 28, samples), 10, 220)
    support_tickets = np.clip(rng.poisson(1.8, samples), 0, 12)
    usage_score = np.clip(rng.normal(62, 22, samples), 0, 100)
    payment_failures = np.clip(rng.poisson(0.45, samples), 0, 6)
    contract_months = rng.choice(
        np.array([1.0, 12.0, 24.0]),
        size=samples,
        p=np.array([0.48, 0.34, 0.18]),
    )
    features = np.column_stack(
        (
            tenure,
            monthly_spend,
            support_tickets,
            usage_score,
            payment_failures,
            contract_months,
        )
    ).astype(np.float64)

    base_logit = (
        0.85
        - (0.035 * tenure)
        + (0.012 * (monthly_spend - 70))
        + (0.33 * support_tickets)
        - (0.028 * (usage_score - 50))
        + (0.58 * payment_failures)
        - (0.055 * contract_months)
    )
    logit = (1.6 * base_logit) + rng.normal(0, 0.35, samples)
    probability = 1.0 / (1.0 + np.exp(-np.clip(logit, -30, 30)))
    labels = rng.binomial(1, probability).astype(np.int64)
    checksum = _dataset_checksum(features, labels, FEATURE_NAMES)
    dataset = Dataset(
        features=features,
        labels=labels,
        feature_names=FEATURE_NAMES,
        checksum=checksum,
        metadata={
            "generator": "synthetic-churn-v1",
            "samples": samples,
            "seed": seed,
            "positive_rate": float(np.mean(labels)),
        },
    )
    validate_dataset(dataset)
    return dataset


def validate_dataset(dataset: Dataset) -> None:
    """Enforce the schema and basic statistical preconditions for training."""

    features = dataset.features
    labels = dataset.labels
    if features.ndim != 2:
        raise ValidationError("features must be a two-dimensional matrix")
    if labels.ndim != 1:
        raise ValidationError("labels must be a one-dimensional vector")
    if features.shape[0] != labels.shape[0]:
        raise ValidationError("features and labels must contain the same row count")
    if features.shape[1] != len(dataset.feature_names):
        raise ValidationError("feature count does not match the declared schema")
    if len(set(dataset.feature_names)) != len(dataset.feature_names):
        raise ValidationError("feature names must be unique")
    if features.shape[0] < 100:
        raise ValidationError("dataset is too small for this reference pipeline")
    if not np.all(np.isfinite(features)):
        raise ValidationError("features contain NaN or infinite values")
    unique_labels = set(int(value) for value in np.unique(labels))
    if unique_labels != {0, 1}:
        raise ValidationError("labels must contain both binary classes 0 and 1")
    positive_rate = float(np.mean(labels))
    if not 0.05 <= positive_rate <= 0.95:
        raise ValidationError("class balance is outside the supported range")


def stratified_split(
    dataset: Dataset,
    test_fraction: float = 0.2,
    seed: int = 42,
) -> tuple[
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.int64],
    NDArray[np.int64],
]:
    """Create a deterministic stratified train/test split."""

    if not 0.1 <= test_fraction <= 0.5:
        raise ValidationError("test_fraction must be between 0.1 and 0.5")

    rng = np.random.default_rng(seed)
    train_indices: list[int] = []
    test_indices: list[int] = []
    for label in (0, 1):
        indices = np.flatnonzero(dataset.labels == label)
        rng.shuffle(indices)
        test_count = max(1, round(len(indices) * test_fraction))
        test_indices.extend(int(index) for index in indices[:test_count])
        train_indices.extend(int(index) for index in indices[test_count:])
    rng.shuffle(train_indices)
    rng.shuffle(test_indices)
    return (
        dataset.features[train_indices],
        dataset.features[test_indices],
        dataset.labels[train_indices],
        dataset.labels[test_indices],
    )
