from __future__ import annotations

from ml_platform_blueprint.domain import CanaryObservation
from ml_platform_blueprint.promotion import CanaryGatePolicy, QualityGatePolicy


def test_offline_quality_gate_explains_each_failure() -> None:
    decision = QualityGatePolicy().evaluate(
        {
            "accuracy": 0.60,
            "f1": 0.50,
            "roc_auc": 0.65,
            "brier_score": 0.30,
            "evaluation_samples": 20.0,
        }
    )

    assert not decision.accepted
    assert set(decision.checks) == {
        "accuracy",
        "f1",
        "roc_auc",
        "brier_score",
        "evaluation_samples",
    }
    assert len(decision.reasons) == 5


def test_online_gate_accepts_healthy_canary() -> None:
    decision = CanaryGatePolicy().evaluate(
        CanaryObservation(
            stable_error_rate=0.01,
            canary_error_rate=0.02,
            stable_p95_ms=100,
            canary_p95_ms=110,
            sample_size=500,
        )
    )

    assert decision.accepted
    assert all(decision.checks.values())


def test_online_gate_rejects_regression() -> None:
    decision = CanaryGatePolicy().evaluate(
        CanaryObservation(
            stable_error_rate=0.01,
            canary_error_rate=0.08,
            stable_p95_ms=100,
            canary_p95_ms=180,
            sample_size=10,
        )
    )

    assert not decision.accepted
    assert len(decision.reasons) == 3
