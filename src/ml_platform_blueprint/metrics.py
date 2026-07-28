"""Binary classification evaluation without a heavyweight ML dependency."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .domain import ValidationError


def _roc_auc(labels: NDArray[np.int64], scores: NDArray[np.float64]) -> float:
    positives = int(np.sum(labels == 1))
    negatives = int(np.sum(labels == 0))
    if positives == 0 or negatives == 0:
        raise ValidationError("ROC AUC requires both classes")

    order = np.argsort(scores, kind="mergesort")
    sorted_scores = scores[order]
    ranks = np.empty(len(scores), dtype=np.float64)
    index = 0
    while index < len(scores):
        end = index + 1
        while end < len(scores) and sorted_scores[end] == sorted_scores[index]:
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        ranks[order[index:end]] = average_rank
        index = end
    positive_rank_sum = float(np.sum(ranks[labels == 1]))
    return (positive_rank_sum - (positives * (positives + 1) / 2.0)) / (positives * negatives)


def evaluate_binary_classifier(
    labels: NDArray[np.int64],
    probabilities: NDArray[np.float64],
    threshold: float = 0.5,
) -> dict[str, float]:
    """Calculate promotion-grade offline metrics."""

    if labels.ndim != 1 or probabilities.ndim != 1:
        raise ValidationError("evaluation values must be one-dimensional")
    if len(labels) != len(probabilities) or len(labels) == 0:
        raise ValidationError("evaluation values must have equal non-zero length")
    if not np.all(np.isfinite(probabilities)):
        raise ValidationError("probabilities contain NaN or infinite values")
    if np.any((probabilities < 0) | (probabilities > 1)):
        raise ValidationError("probabilities must be in [0, 1]")

    predictions = (probabilities >= threshold).astype(np.int64)
    true_positive = int(np.sum((labels == 1) & (predictions == 1)))
    true_negative = int(np.sum((labels == 0) & (predictions == 0)))
    false_positive = int(np.sum((labels == 0) & (predictions == 1)))
    false_negative = int(np.sum((labels == 1) & (predictions == 0)))

    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    accuracy = (true_positive + true_negative) / len(labels)
    brier = float(np.mean((probabilities - labels) ** 2))
    return {
        "accuracy": float(accuracy),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "roc_auc": float(_roc_auc(labels, probabilities)),
        "brier_score": brier,
        "true_positive": float(true_positive),
        "true_negative": float(true_negative),
        "false_positive": float(false_positive),
        "false_negative": float(false_negative),
        "evaluation_samples": float(len(labels)),
    }
