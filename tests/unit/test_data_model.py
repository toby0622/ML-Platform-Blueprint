from __future__ import annotations

import numpy as np
import pytest

from ml_platform_blueprint.data import (
    Dataset,
    generate_churn_dataset,
    stratified_split,
    validate_dataset,
)
from ml_platform_blueprint.domain import ValidationError
from ml_platform_blueprint.metrics import evaluate_binary_classifier
from ml_platform_blueprint.model import (
    ModelArtifact,
    predict_probabilities,
    train_logistic_regression,
)


def test_dataset_is_reproducible_and_content_addressed() -> None:
    first = generate_churn_dataset(samples=300, seed=7)
    second = generate_churn_dataset(samples=300, seed=7)
    changed = generate_churn_dataset(samples=300, seed=8)

    assert first.checksum == second.checksum
    assert first.checksum != changed.checksum
    np.testing.assert_array_equal(first.features, second.features)
    np.testing.assert_array_equal(first.labels, second.labels)


def test_schema_validation_rejects_non_finite_features() -> None:
    original = generate_churn_dataset(samples=100)
    broken_features = original.features.copy()
    broken_features[0, 0] = np.nan
    broken = Dataset(
        features=broken_features,
        labels=original.labels,
        feature_names=original.feature_names,
        checksum=original.checksum,
        metadata=original.metadata,
    )

    with pytest.raises(ValidationError, match="NaN"):
        validate_dataset(broken)


def test_model_round_trip_and_metrics() -> None:
    dataset = generate_churn_dataset()
    train_x, test_x, train_y, test_y = stratified_split(dataset)
    artifact = train_logistic_regression(train_x, train_y, dataset.feature_names)
    restored = ModelArtifact.from_dict(artifact.to_dict())
    probabilities = predict_probabilities(restored, test_x)
    metrics = evaluate_binary_classifier(test_y, probabilities)

    assert metrics["accuracy"] >= 0.72
    assert metrics["f1"] >= 0.68
    assert metrics["roc_auc"] >= 0.78
    assert metrics["brier_score"] <= 0.20
    np.testing.assert_allclose(probabilities, predict_probabilities(artifact, test_x), atol=1e-12)
