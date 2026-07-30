from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from ml_platform_blueprint.cli import _settings, build_parser, main


def invoke(
    state_dir: Path,
    capsys: pytest.CaptureFixture[str],
    *arguments: str,
    expected: int = 0,
) -> dict[str, Any]:
    result = main(["--state-dir", str(state_dir), *arguments])
    captured = capsys.readouterr()
    assert result == expected, captured
    return json.loads(captured.out)


def test_cli_settings_use_environment_state_dir_when_flag_is_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_state = tmp_path / "from-environment"
    monkeypatch.setenv("ML_PLATFORM_STATE_DIR", str(environment_state))

    settings = _settings(build_parser().parse_args(["init"]))

    assert settings.state_dir == environment_state


def test_cli_state_dir_flag_overrides_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit_state = tmp_path / "explicit"
    monkeypatch.setenv("ML_PLATFORM_STATE_DIR", str(tmp_path / "from-environment"))

    settings = _settings(build_parser().parse_args(["--state-dir", str(explicit_state), "init"]))

    assert settings.state_dir == explicit_state


def test_cli_settings_preserve_otel_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "http://collector:4318/v1/traces",
    )
    monkeypatch.setenv("OTEL_SERVICE_NAME", "cli-test-service")

    settings = _settings(build_parser().parse_args(["serve"]))

    assert settings.otel_traces_endpoint == "http://collector:4318/v1/traces"
    assert settings.otel_service_name == "cli-test-service"


def test_cli_operates_complete_lifecycle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    initialized = invoke(tmp_path, capsys, "init")
    assert initialized["status"] == "initialized"
    assert invoke(tmp_path, capsys, "status")["deployment"] is None

    baseline = invoke(tmp_path, capsys, "train")
    assert baseline["model_version"]["version"] == 1
    invoke(
        tmp_path,
        capsys,
        "promote",
        "--version",
        "1",
        "--actor",
        "cli-test",
        "--reason",
        "establish baseline",
    )
    prediction = invoke(tmp_path, capsys, "predict", "--request-id", "cli-1")
    assert prediction["model_version"] == 1

    candidate = invoke(
        tmp_path,
        capsys,
        "train",
        "--epochs",
        "900",
        "--l2",
        "0.005",
    )
    assert candidate["model_version"]["version"] == 2
    invoke(
        tmp_path,
        capsys,
        "promote",
        "--version",
        "2",
        "--canary-weight",
        "20",
        "--actor",
        "cli-test",
        "--reason",
        "candidate passed offline policy",
    )
    finalized = invoke(
        tmp_path,
        capsys,
        "finalize",
        "--stable-error-rate",
        "0.01",
        "--canary-error-rate",
        "0.012",
        "--stable-p95-ms",
        "40",
        "--canary-p95-ms",
        "42",
        "--sample-size",
        "200",
        "--actor",
        "cli-test",
        "--reason",
        "candidate passed online policy",
    )
    assert finalized["deployment"]["stable_version"] == 2

    rolled_back = invoke(
        tmp_path,
        capsys,
        "rollback",
        "--target-version",
        "1",
        "--actor",
        "cli-test",
        "--reason",
        "exercise manual rollback",
    )
    assert rolled_back["deployment"]["stable_version"] == 1
    assert len(invoke(tmp_path, capsys, "audit")["items"]) >= 6
    assert len(invoke(tmp_path, capsys, "status")["versions"]) == 2


def test_cli_demo_and_structured_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = invoke(tmp_path / "demo", capsys, "demo")
    assert demo["finalized_deployment"]["deployment"]["stable_version"] == 2

    missing = invoke(
        tmp_path / "errors",
        capsys,
        "promote",
        "--version",
        "99",
        expected=1,
    )
    assert missing["error"] == "not_found"

    rejected_run = invoke(
        tmp_path / "rejected",
        capsys,
        "train",
        "--decision-threshold",
        "0.99",
    )
    rejected = invoke(
        tmp_path / "rejected",
        capsys,
        "promote",
        "--version",
        str(rejected_run["model_version"]["version"]),
        expected=2,
    )
    assert rejected["error"] == "quality_gate_rejected"

    invalid = invoke(
        tmp_path / "invalid",
        capsys,
        "--model",
        "Not-A-DNS-Label",
        "train",
        expected=1,
    )
    assert invalid["error"] == "invalid_input"

    malformed = invoke(
        tmp_path / "malformed",
        capsys,
        "predict",
        "--instance",
        "{",
        expected=1,
    )
    assert malformed["error"] == "invalid_input"

    with pytest.raises(SystemExit):
        main(
            [
                "--state-dir",
                str(tmp_path / "array"),
                "predict",
                "--instance",
                "[]",
            ]
        )


def test_cli_serve_builds_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_run(app: Any, *, host: str, port: int, access_log: bool) -> None:
        observed.update(app=app, host=host, port=port, access_log=access_log)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    assert (
        main(
            [
                "--state-dir",
                str(tmp_path),
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "9091",
                "--no-access-log",
            ]
        )
        == 0
    )
    assert observed["host"] == "127.0.0.1"
    assert observed["port"] == 9091
    assert observed["access_log"] is False
