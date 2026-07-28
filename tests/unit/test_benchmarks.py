from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def load_module(name: str, path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_load_summary_percentiles() -> None:
    module = load_module("load_benchmark", "benchmarks/load/run.py")
    samples = [
        module.Sample(10.0, 200, "stable", "1"),
        module.Sample(20.0, 200, "canary", "2"),
        module.Sample(30.0, 500, "error", "unknown", "HTTP 500"),
    ]
    summary = module.summarize(samples, 1.0)

    assert summary["requests"] == 3
    assert summary["availability"] == pytest.approx(2 / 3)
    assert summary["latency_ms"]["p50"] == 20.0
    assert summary["routes"] == {"stable": 1, "canary": 1}


def test_vllm_summary_and_scenario_configuration() -> None:
    module = load_module("vllm_benchmark", "benchmarks/inference/vllm_benchmark.py")
    samples = [
        module.LlmSample(
            run_number=1,
            concurrency=2,
            prompt_id=0,
            success=True,
            ttft_ms=10,
            end_to_end_ms=40,
            mean_itl_ms=5,
            prompt_tokens=4,
            completion_tokens=8,
            error=None,
        ),
        module.LlmSample(
            run_number=1,
            concurrency=2,
            prompt_id=1,
            success=False,
            ttft_ms=0,
            end_to_end_ms=20,
            mean_itl_ms=0,
            prompt_tokens=0,
            completion_tokens=0,
            error="HTTPStatusError",
        ),
    ]
    summary = module.summarize(samples, 2.0)
    configuration, scenario = module.load_scenario(
        Path("benchmarks/inference/configs.yaml"),
        "prefix-cache",
    )

    assert summary["error_rate"] == 0.5
    assert summary["output_throughput_tokens_per_second"] == 4
    assert summary["total_throughput_tokens_per_second"] == 6
    assert summary["ttft_ms"]["p95"] == 10
    assert configuration["runs_per_scenario"] == 3
    assert scenario["engine_args"]["enable_prefix_caching"] is True


def test_vllm_quality_gate_rejects_a_bad_high_concurrency_slice() -> None:
    module = load_module("vllm_quality_gate", "benchmarks/inference/vllm_benchmark.py")
    gate = module.evaluate_quality_gate(
        warmup_failures=0,
        aggregate_error_rate=0.005,
        results_by_concurrency={
            "1": {"error_rate": 0.0},
            "16": {"error_rate": 0.05},
        },
        results_by_run=[
            {
                "run_number": 1,
                "results_by_concurrency": {
                    "1": {"error_rate": 0.0},
                    "16": {"error_rate": 0.05},
                },
            }
        ],
        max_error_rate=0.01,
    )

    assert gate["passed"] is False
    assert {violation["scope"] for violation in gate["violations"]} == {
        "concurrency",
        "run_concurrency",
    }


def test_gpu_evidence_uses_three_run_median_and_range() -> None:
    module = load_module(
        "publish_gpu_evidence",
        "benchmarks/inference/publish_evidence.py",
    )

    def summary(value: float) -> dict:
        return {
            "request_throughput_rps": value,
            "output_throughput_tokens_per_second": value,
            "ttft_ms": {"p50": value, "p95": value},
            "end_to_end_ms": {"p50": value, "p95": value},
            "mean_itl_ms": value,
        }

    distribution = module.metric_distribution([summary(3.0), summary(1.0), summary(2.0)])

    assert distribution["ttft_p95_ms"] == {
        "median": 2.0,
        "min": 1.0,
        "max": 3.0,
    }


def test_rtx_4080_super_scenario_maps_to_safe_compose_environment() -> None:
    module = load_module(
        "local_gpu_benchmark",
        "benchmarks/inference/run_local_gpu.py",
    )
    configuration, scenario = module.load_scenario(
        Path("benchmarks/inference/configs-rtx4080-super.yaml"),
        "constrained-batch",
    )

    environment = module.scenario_environment(scenario)

    assert configuration["profile"]["id"] == "local-rtx4080-super-16gb"
    assert environment == {
        "VLLM_ENABLE_PREFIX_CACHING": "false",
        "VLLM_GPU_MEMORY_UTILIZATION": "0.75",
        "VLLM_MAX_MODEL_LEN": "4096",
        "VLLM_MAX_NUM_BATCHED_TOKENS": "128",
    }


def test_local_gpu_env_loader_excludes_tokens(tmp_path: Path) -> None:
    module = load_module(
        "local_gpu_environment",
        "benchmarks/inference/run_local_gpu.py",
    )
    env_file = tmp_path / "gpu.env"
    env_file.write_text(
        "\n".join(
            (
                "VLLM_MODEL='example/model'",
                "export VLLM_QUANTIZATION=awq",
                "HF_TOKEN=must-not-enter-benchmark-metadata",
                "POSTGRES_PASSWORD=must-not-enter-benchmark-metadata",
            )
        ),
        encoding="utf-8",
    )

    values = module.load_vllm_environment(env_file)

    assert values == {
        "VLLM_MODEL": "example/model",
        "VLLM_QUANTIZATION": "awq",
    }


def test_explicit_model_does_not_inherit_a_stale_revision() -> None:
    module = load_module(
        "local_gpu_model_revision",
        "benchmarks/inference/run_local_gpu.py",
    )

    revision = module.resolve_model_revision(
        model="another/model",
        explicit_model="another/model",
        explicit_revision=None,
        environment={"VLLM_MODEL_REVISION": "revision-for-old-model"},
    )

    assert revision == ""


def test_local_gpu_runner_finds_per_user_docker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_module(
        "local_gpu_docker_discovery",
        "benchmarks/inference/run_local_gpu.py",
    )
    docker = tmp_path / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
    docker.parent.mkdir(parents=True)
    docker.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)

    assert module.find_docker_executable() == str(docker)


def test_local_gpu_runner_adds_docker_helpers_to_stale_path(tmp_path: Path) -> None:
    module = load_module(
        "local_gpu_docker_path",
        "benchmarks/inference/run_local_gpu.py",
    )
    docker = tmp_path / "DockerDesktop" / "resources" / "bin" / "docker.exe"
    docker.parent.mkdir(parents=True)
    docker.write_bytes(b"")

    environment = module.with_docker_on_path({"PATH": "C:\\Windows"}, str(docker))

    assert environment["PATH"].split(module.os.pathsep)[0] == str(docker.parent.resolve())
    assert environment["PATH"].endswith("C:\\Windows")


def test_cost_calculation_is_dimensionally_consistent() -> None:
    module = load_module("cost_calculator", "benchmarks/cost/calculate.py")
    result = module.calculate(
        {
            "gpu_hourly_cost_usd": 1.0,
            "output_tokens_per_second": 100.0,
            "target_utilization": 0.5,
            "average_output_tokens_per_request": 500.0,
            "replicas": 2.0,
        }
    )

    assert result["fleet_tokens_per_hour"] == 360_000
    assert result["fleet_hourly_cost_usd"] == 2
    assert result["cost_per_million_output_tokens_usd"] == pytest.approx(5.5555556)

    with pytest.raises(ValueError):
        module.calculate(
            {
                "gpu_hourly_cost_usd": 1.0,
                "output_tokens_per_second": 100.0,
                "target_utilization": 1.5,
                "average_output_tokens_per_request": 500.0,
                "replicas": 1.0,
            }
        )
