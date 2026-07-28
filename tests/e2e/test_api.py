from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ml_platform_blueprint.api import create_app
from ml_platform_blueprint.config import Settings

INSTANCE = {
    "tenure_months": 12.0,
    "monthly_spend": 90.0,
    "support_tickets": 2.0,
    "usage_score": 55.0,
    "payment_failures": 1.0,
    "contract_months": 1.0,
}


def client_for(path: Path) -> TestClient:
    app = create_app(
        Settings(
            state_dir=path,
            code_revision="api-test",
            environment="test",
        )
    )
    return TestClient(app)


def test_api_runs_train_promote_predict_flow(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").status_code == 200

        train = client.post(
            "/v1/tenants/team-a/models/churn/runs",
            headers={"X-Tenant-Id": "team-a"},
            json={},
        )
        assert train.status_code == 201, train.text
        version = train.json()["model_version"]["version"]

        promote = client.post(
            f"/v1/tenants/team-a/models/churn/versions/{version}/promotion",
            headers={"X-Tenant-Id": "team-a"},
            json={
                "canary_weight": 10,
                "actor": "api-test",
                "reason": "acceptance test",
            },
        )
        assert promote.status_code == 200, promote.text

        prediction = client.post(
            "/v1/tenants/team-a/models/churn/predict",
            headers={"X-Tenant-Id": "team-a"},
            json={"request_id": "api-test-1", "instances": [INSTANCE]},
        )
        assert prediction.status_code == 200, prediction.text
        assert prediction.json()["model_version"] == version
        assert len(prediction.json()["predictions"]) == 1

        header_prediction = client.post(
            "/v1/tenants/team-a/models/churn/predict",
            headers={
                "X-Tenant-Id": "team-a",
                "X-Request-Id": "benchmark-request-1",
            },
            json={"instances": [INSTANCE]},
        )
        assert header_prediction.status_code == 200, header_prediction.text
        assert header_prediction.json()["request_id"] == "benchmark-request-1"

        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "ml_platform_predictions_total" in metrics.text


def test_api_rejects_tenant_header_mismatch(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        response = client.post(
            "/v1/tenants/team-a/models/churn/runs",
            headers={"X-Tenant-Id": "team-b"},
            json={},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "tenant_access_denied"


def test_api_exposes_lineage_finalize_rollback_and_structured_errors(
    tmp_path: Path,
) -> None:
    headers = {"X-Tenant-Id": "team-a"}
    with client_for(tmp_path) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert root.json()["environment"] == "test"

        missing = client.get("/v1/runs/missing")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"

        baseline = client.post(
            "/v1/tenants/team-a/models/churn/runs",
            headers=headers,
            json={},
        ).json()
        run_id = baseline["run_id"]
        assert client.get(f"/v1/runs/{run_id}").json()["status"] == "succeeded"
        assert (
            client.get("/v1/tenants/team-a/models/churn/versions", headers=headers).json()["items"][
                0
            ]["version"]
            == 1
        )
        assert (
            client.get("/v1/tenants/team-a/models/churn/versions/1", headers=headers).json()[
                "artifact_sha256"
            ]
            == baseline["model_version"]["artifact_sha256"]
        )
        client.post(
            "/v1/tenants/team-a/models/churn/versions/1/promotion",
            headers=headers,
            json={"actor": "api-test", "reason": "establish baseline"},
        )
        assert (
            client.get("/v1/tenants/team-a/models/churn/deployment", headers=headers).json()[
                "stable_version"
            ]
            == 1
        )

        client.post(
            "/v1/tenants/team-a/models/churn/runs",
            headers=headers,
            json={"epochs": 900, "l2": 0.005},
        )
        client.post(
            "/v1/tenants/team-a/models/churn/versions/2/promotion",
            headers=headers,
            json={
                "canary_weight": 20,
                "actor": "api-test",
                "reason": "candidate passed offline gate",
            },
        )
        finalize = client.post(
            "/v1/tenants/team-a/models/churn/deployment/finalize",
            headers=headers,
            json={
                "stable_error_rate": 0.01,
                "canary_error_rate": 0.012,
                "stable_p95_ms": 40,
                "canary_p95_ms": 42,
                "sample_size": 200,
                "actor": "api-test",
                "reason": "candidate passed online gate",
            },
        )
        assert finalize.status_code == 200
        assert finalize.json()["deployment"]["stable_version"] == 2

        rollback = client.post(
            "/v1/tenants/team-a/models/churn/deployment/rollback",
            headers=headers,
            json={
                "target_version": 1,
                "actor": "api-test",
                "reason": "exercise rollback route",
            },
        )
        assert rollback.status_code == 200
        assert rollback.json()["deployment"]["stable_version"] == 1
        audit = client.get("/v1/tenants/team-a/models/churn/audit?limit=10", headers=headers)
        assert audit.status_code == 200
        assert audit.json()["items"][0]["event_type"] == "manual_rollback"

        invalid_name = client.post(
            "/v1/tenants/team-a/models/Not-Valid/runs",
            headers=headers,
            json={},
        )
        assert invalid_name.status_code == 422
        assert invalid_name.json()["error"]["code"] == "invalid_resource_name"
