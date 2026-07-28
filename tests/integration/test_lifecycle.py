from __future__ import annotations

from pathlib import Path

import pytest

from ml_platform_blueprint.config import Settings
from ml_platform_blueprint.domain import (
    CanaryObservation,
    ConflictError,
    GateRejectedError,
    NotFoundError,
    TenantAccessError,
)
from ml_platform_blueprint.service import PlatformService, TrainingParameters

INSTANCE = {
    "tenure_months": 12.0,
    "monthly_spend": 90.0,
    "support_tickets": 2.0,
    "usage_score": 55.0,
    "payment_failures": 1.0,
    "contract_months": 1.0,
}


def make_service(state_dir: Path) -> PlatformService:
    return PlatformService(
        Settings(
            state_dir=state_dir,
            code_revision="test-revision",
            environment="test",
        )
    )


@pytest.mark.integration
def test_complete_lifecycle_with_canary_and_finalize(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    first = service.train_and_register(tenant="team-a", model_name="churn")
    first_version = first["model_version"]["version"]
    initial = service.promote(
        tenant="team-a",
        model_name="churn",
        version=first_version,
        canary_weight=10,
        actor="pytest",
        reason="establish baseline",
    )
    assert initial["deployment"]["stable_version"] == 1
    assert initial["deployment"]["canary_version"] is None

    second = service.train_and_register(
        tenant="team-a",
        model_name="churn",
        parameters=TrainingParameters(epochs=900, l2=0.005),
    )
    canary = service.promote(
        tenant="team-a",
        model_name="churn",
        version=second["model_version"]["version"],
        canary_weight=20,
        actor="pytest",
        reason="offline metrics passed",
    )
    assert canary["deployment"]["stable_version"] == 1
    assert canary["deployment"]["canary_version"] == 2

    routes = {
        service.predict(
            tenant="team-a",
            model_name="churn",
            instances=[INSTANCE],
            request_id=f"request-{index}",
        )["route"]
        for index in range(100)
    }
    assert routes == {"stable", "canary"}

    result = service.finalize_canary(
        tenant="team-a",
        model_name="churn",
        observation=CanaryObservation(
            stable_error_rate=0.01,
            canary_error_rate=0.012,
            stable_p95_ms=50,
            canary_p95_ms=54,
            sample_size=1000,
        ),
        actor="pytest",
        reason="online metrics passed",
    )
    assert result["deployment"]["stable_version"] == 2
    assert result["deployment"]["canary_version"] is None
    assert service.registry.get_alias("team-a", "churn", "champion") == 2

    events = service.registry.list_audit_events("team-a", "churn")
    assert {event["event_type"] for event in events} >= {
        "model_registered",
        "initial_model_promoted",
        "canary_started",
        "canary_finalized",
    }


@pytest.mark.integration
def test_bad_canary_is_automatically_rolled_back(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.train_and_register(tenant="team-a", model_name="churn")
    service.promote(
        tenant="team-a",
        model_name="churn",
        version=1,
        canary_weight=10,
        actor="pytest",
        reason="baseline",
    )
    service.train_and_register(tenant="team-a", model_name="churn")
    service.promote(
        tenant="team-a",
        model_name="churn",
        version=2,
        canary_weight=10,
        actor="pytest",
        reason="candidate",
    )

    with pytest.raises(GateRejectedError, match="rollback completed"):
        service.finalize_canary(
            tenant="team-a",
            model_name="churn",
            observation=CanaryObservation(
                stable_error_rate=0.01,
                canary_error_rate=0.20,
                stable_p95_ms=40,
                canary_p95_ms=100,
                sample_size=1000,
            ),
            actor="pytest",
            reason="automated SLI evaluation",
        )

    deployment = service.registry.get_deployment("team-a", "churn")
    assert deployment.stable_version == 1
    assert deployment.canary_version is None
    assert (
        service.registry.list_audit_events("team-a", "churn")[0]["event_type"]
        == "canary_auto_rollback"
    )


@pytest.mark.integration
def test_failed_offline_gate_cannot_promote(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    run = service.train_and_register(
        tenant="team-a",
        model_name="churn",
        parameters=TrainingParameters(decision_threshold=0.99),
    )
    with pytest.raises(GateRejectedError):
        service.promote(
            tenant="team-a",
            model_name="churn",
            version=run["model_version"]["version"],
            canary_weight=10,
            actor="pytest",
            reason="test rejection",
        )
    with pytest.raises(NotFoundError):
        service.registry.get_deployment("team-a", "churn")
    assert (
        service.registry.list_audit_events("team-a", "churn")[0]["event_type"]
        == "promotion_rejected"
    )


@pytest.mark.integration
def test_artifact_tampering_is_detected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.train_and_register(tenant="team-a", model_name="churn")
    record = service.registry.get_version("team-a", "churn", 1)
    artifact_path = service.registry.state_dir / record.artifact_path
    artifact_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ConflictError, match="integrity"):
        service.registry.load_artifact("team-a", "churn", 1)


def test_tenant_allowlist_is_enforced(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    with pytest.raises(TenantAccessError):
        service.train_and_register(tenant="team-c", model_name="churn")
