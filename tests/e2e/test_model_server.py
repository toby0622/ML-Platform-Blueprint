from __future__ import annotations

from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from ml_platform_blueprint.config import Settings
from ml_platform_blueprint.model_server import create_model_app, main
from ml_platform_blueprint.service import PlatformService

INSTANCE = {
    "tenure_months": 12.0,
    "monthly_spend": 90.0,
    "support_tickets": 2.0,
    "usage_score": 55.0,
    "payment_failures": 1.0,
    "contract_months": 1.0,
}


def model_client(tmp_path: Path) -> TestClient:
    service = PlatformService(Settings(state_dir=tmp_path, code_revision="model-server-test"))
    result = service.train_and_register(tenant="team-a", model_name="churn")
    record = service.registry.get_version("team-a", "churn", 1)
    app = create_model_app(
        artifact_path=service.registry.state_dir / record.artifact_path,
        expected_sha256=result["model_version"]["artifact_sha256"],
        model_name="churn",
        model_version="1",
    )
    return TestClient(app)


def test_kserve_v1_protocol(tmp_path: Path) -> None:
    with model_client(tmp_path) as client:
        response = client.post("/v1/models/churn:predict", json={"instances": [INSTANCE]})

    assert response.status_code == 200
    assert response.json()["model_version"] == "1"
    assert 0 <= response.json()["predictions"][0]["probability"] <= 1


def test_kserve_v2_protocol(tmp_path: Path) -> None:
    with model_client(tmp_path) as client:
        response = client.post(
            "/v2/models/churn/infer",
            json={
                "id": "v2-test",
                "inputs": [
                    {
                        "name": "features",
                        "shape": [1, 6],
                        "datatype": "FP64",
                        "data": [list(INSTANCE.values())],
                    }
                ],
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == "v2-test"
    assert {output["name"] for output in response.json()["outputs"]} == {
        "probabilities",
        "labels",
    }


def test_model_server_health_metadata_validation_and_metrics(tmp_path: Path) -> None:
    with model_client(tmp_path) as client:
        for path in (
            "/healthz",
            "/readyz",
            "/v2/health/live",
            "/v2/health/ready",
            "/v1/models/churn",
            "/v2/models/churn",
            "/v2/models/churn/ready",
        ):
            assert client.get(path).status_code == 200
        assert client.get("/v2/models/missing/ready").status_code == 404
        assert (
            client.post(
                "/v1/models/churn:predict",
                json={"instances": [[1.0, 2.0]]},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/v2/models/churn/infer",
                json={
                    "inputs": [
                        {
                            "name": "other",
                            "shape": [1, 6],
                            "datatype": "FP64",
                            "data": [[1, 2, 3, 4, 5, 6]],
                        }
                    ]
                },
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/v2/models/churn/infer",
                json={
                    "inputs": [
                        {
                            "name": "features",
                            "shape": [1, 6],
                            "datatype": "INT64",
                            "data": [[1, 2, 3, 4, 5, 6]],
                        }
                    ]
                },
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/v2/models/churn/infer",
                json={
                    "inputs": [
                        {
                            "name": "features",
                            "shape": [1, 6],
                            "datatype": "FP64",
                            "data": [[1, 2]],
                        }
                    ]
                },
            ).status_code
            == 400
        )
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "model_server_requests_total" in metrics.text


def test_model_server_rejects_missing_or_tampered_artifact(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(RuntimeError, match="does not exist"):
        create_model_app(artifact_path=missing)
    assert main(["--artifact", str(missing)]) == 1

    service = PlatformService(Settings(state_dir=tmp_path / "state"))
    service.train_and_register(tenant="team-a", model_name="churn")
    record = service.registry.get_version("team-a", "churn", 1)
    artifact = service.registry.state_dir / record.artifact_path
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        create_model_app(artifact_path=artifact, expected_sha256="0" * 64)


def test_model_server_main_starts_valid_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = PlatformService(Settings(state_dir=tmp_path / "state"))
    service.train_and_register(tenant="team-a", model_name="churn")
    record = service.registry.get_version("team-a", "churn", 1)
    artifact = service.registry.state_dir / record.artifact_path
    observed: dict[str, object] = {}

    def fake_run(app: object, *, host: str, port: int) -> None:
        observed.update(app=app, host=host, port=port)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    assert (
        main(
            [
                "--artifact",
                str(artifact),
                "--model-name",
                "churn",
                "--model-version",
                "1",
                "--host",
                "127.0.0.1",
                "--port",
                "9092",
            ]
        )
        == 0
    )
    assert observed["host"] == "127.0.0.1"
    assert observed["port"] == 9092
