from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ml_platform_blueprint.api import create_app
from ml_platform_blueprint.config import Settings


class RecordingSpanExporter(InMemorySpanExporter):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        super().shutdown()


def test_fastapi_exports_otlp_spans_and_excludes_health_endpoints(tmp_path: Path) -> None:
    exporter = RecordingSpanExporter()
    application = create_app(
        Settings(
            state_dir=tmp_path,
            code_revision="trace-test",
            environment="test",
            otel_traces_endpoint="http://unused.example/v1/traces",
            otel_service_name="trace-test-service",
        ),
        span_exporter=exporter,
    )

    with TestClient(application) as client:
        assert client.get("/").status_code == 200
        assert client.get("/healthz").status_code == 200

    spans = exporter.get_finished_spans()
    server_spans = [span for span in spans if span.kind.name == "SERVER"]
    assert len(server_spans) == 1
    assert server_spans[0].attributes["http.route"] == "/"
    assert server_spans[0].resource.attributes["service.name"] == "trace-test-service"
    assert server_spans[0].resource.attributes["deployment.environment.name"] == "test"
    assert exporter.shutdown_calls == 1


def test_general_otlp_endpoint_is_normalized_for_traces(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ML_PLATFORM_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/")

    settings = Settings.from_env()

    assert settings.otel_traces_endpoint == "http://collector:4318/v1/traces"
