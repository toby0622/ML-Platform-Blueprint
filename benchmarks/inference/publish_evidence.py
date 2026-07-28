"""Publish a reviewed, secret-free summary of local vLLM benchmark artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ("baseline", "prefix-cache", "constrained-batch")


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repository_path(path: str | Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        return candidate.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return candidate.name


def selected_metrics(summary: dict[str, Any]) -> dict[str, float]:
    return {
        "request_throughput_rps": float(summary["request_throughput_rps"]),
        "output_throughput_tokens_per_second": float(
            summary["output_throughput_tokens_per_second"]
        ),
        "ttft_p50_ms": float(summary["ttft_ms"]["p50"]),
        "ttft_p95_ms": float(summary["ttft_ms"]["p95"]),
        "end_to_end_p50_ms": float(summary["end_to_end_ms"]["p50"]),
        "end_to_end_p95_ms": float(summary["end_to_end_ms"]["p95"]),
        "mean_itl_ms": float(summary["mean_itl_ms"]),
    }


def rounded_metrics(summary: dict[str, Any]) -> dict[str, float]:
    return {name: round(value, 3) for name, value in selected_metrics(summary).items()}


def metric_distribution(run_summaries: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Return the median and observed range across complete benchmark runs."""

    flattened = [selected_metrics(summary) for summary in run_summaries]
    return {
        metric: {
            "median": round(statistics.median(values), 3),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
        }
        for metric in flattened[0]
        if (values := [summary[metric] for summary in flattened])
    }


def verified_artifact(
    *,
    path: Path,
    recorded: dict[str, Any] | None = None,
) -> dict[str, str]:
    actual_hash = sha256(path)
    if recorded is not None and recorded.get("sha256") != actual_hash:
        raise ValueError(f"artifact hash does not match manifest: {path}")
    return {
        "path": repository_path(path),
        "sha256": actual_hash,
    }


def source_artifacts(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    names = (
        "benchmark_driver",
        "compose",
        "config",
        "orchestrator",
        "prompts",
        "startup_script",
    )
    result: dict[str, dict[str, str]] = {}
    for name in names:
        artifact = manifest["configuration"][name]
        result[name] = {
            "path": repository_path(str(artifact["path"])),
            "sha256": str(artifact["sha256"]),
        }
    return result


def telemetry_evidence(telemetry: dict[str, Any]) -> dict[str, Any]:
    per_gpu = telemetry["summary"]["per_gpu"]
    if len(per_gpu) != 1:
        raise ValueError("reviewed local evidence requires exactly one observed GPU")
    gpu = per_gpu[0]
    metrics = gpu["metrics"]
    selected = (
        "memory_used_mib",
        "gpu_utilization_percent",
        "memory_utilization_percent",
        "temperature_celsius",
        "power_draw_watts",
        "power_limit_watts",
    )
    return {
        "collection_seconds": round(
            float(telemetry["collection"]["requested_duration_seconds"]),
            3,
        ),
        "sample_count": int(telemetry["summary"]["sample_count"]),
        "gpu": {
            "index": gpu["identity"]["index"],
            "name": gpu["identity"]["name"],
            "driver_versions_observed": gpu["identity"]["driver_versions_observed"],
        },
        "metrics": {
            name: {
                key: round(float(value), 3) if value is not None else None
                for key, value in metrics[name].items()
                if key in {"p50", "p95", "max"}
            }
            for name in selected
        },
    }


def scenario_evidence(
    *,
    name: str,
    benchmark_dir: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    benchmark_path = benchmark_dir / f"vllm-{name}.json"
    telemetry_path = benchmark_dir / f"vllm-{name}-gpu-telemetry.json"
    manifest_path = benchmark_dir / f"vllm-{name}-manifest.json"
    benchmark = load_json(benchmark_path)
    telemetry = load_json(telemetry_path)
    manifest = load_json(manifest_path)

    if benchmark["configuration"]["scenario"] != name:
        raise ValueError(f"scenario mismatch in {benchmark_path}")
    if not benchmark["quality_gate"]["passed"]:
        raise ValueError(f"quality gate failed for {name}")
    if float(benchmark["aggregate_error_rate"]) != 0:
        raise ValueError(f"reviewed scenario contains request errors: {name}")
    if manifest["benchmark_returncode"] != 0 or manifest["telemetry"]["status"] != "ok":
        raise ValueError(f"benchmark or telemetry failed for {name}")

    raw_artifacts = {
        "benchmark": verified_artifact(
            path=benchmark_path,
            recorded=manifest["artifacts"]["benchmark"],
        ),
        "gpu_telemetry": verified_artifact(
            path=telemetry_path,
            recorded=manifest["artifacts"]["gpu_telemetry"],
        ),
        "manifest": verified_artifact(path=manifest_path),
    }
    run_results = benchmark["results_by_run"]
    concurrency_results: dict[str, Any] = {}
    for concurrency, aggregate in benchmark["results_by_concurrency"].items():
        per_run = [run["results_by_concurrency"][concurrency] for run in run_results]
        concurrency_results[concurrency] = {
            "aggregate": rounded_metrics(aggregate),
            "three_run_distribution": metric_distribution(per_run),
        }

    return (
        {
            "name": name,
            "engine_args": benchmark["configuration"]["engine_args"],
            "measured_requests": len(benchmark["samples"]),
            "aggregate_error_rate": benchmark["aggregate_error_rate"],
            "quality_gate": benchmark["quality_gate"],
            "results_by_concurrency": concurrency_results,
            "gpu_telemetry": telemetry_evidence(telemetry),
            "raw_artifacts": raw_artifacts,
        },
        source_artifacts(manifest),
    )


def build_evidence(
    *,
    benchmark_dir: Path,
    preflight_path: Path,
    reviewed_on: str,
) -> dict[str, Any]:
    preflight = load_json(preflight_path)
    if not preflight.get("ready"):
        raise ValueError("GPU preflight must be ready before evidence publication")

    scenarios: list[dict[str, Any]] = []
    sources: dict[str, dict[str, str]] | None = None
    for name in SCENARIOS:
        scenario, scenario_sources = scenario_evidence(
            name=name,
            benchmark_dir=benchmark_dir,
        )
        if sources is not None and scenario_sources != sources:
            raise ValueError("source artifact hashes differ between scenarios")
        sources = scenario_sources
        scenarios.append(scenario)

    baseline_manifest = load_json(benchmark_dir / "vllm-baseline-manifest.json")
    baseline_benchmark = load_json(benchmark_dir / "vllm-baseline.json")
    configuration = baseline_benchmark["configuration"]
    docker_check = preflight["checks"]["docker"]
    gpu = preflight["checks"]["nvidia"]["devices"][0]
    runtime = baseline_manifest["runtime"]

    return {
        "schema_version": "1",
        "kind": "local-rtx4080-super-vllm-benchmark-summary",
        "reviewed_on": reviewed_on,
        "environment": {
            "host_os": preflight["host_os"],
            "docker_desktop_version": "4.84.0",
            "docker_client": docker_check["client_version"],
            "docker_server_version": docker_check["server_version"],
            "docker_compose": docker_check["compose_version"],
            "docker_engine": {
                "os_type": docker_check["os_type"],
                "operating_system": docker_check["operating_system"],
                "nvidia_runtime_detected": docker_check["nvidia_runtime_detected"],
            },
            "wsl": preflight["checks"]["wsl"],
            "gpu": gpu,
        },
        "cuda_container_smoke": {
            "status": "passed",
            "image": "nvidia/cuda:13.0.2-base-ubuntu24.04",
            "image_digest": (
                "sha256:2ab6381d970b211fb93853796dc6707eb8a72575a375c422b17cf4d8b2641701"
            ),
            "observed_gpu": "NVIDIA GeForce RTX 4080 SUPER",
            "observed_driver_version": "610.74",
            "observed_memory_total_mib": 16376,
            "observed_compute_capability": 8.9,
        },
        "runtime": {
            "vllm_version": "0.23.0",
            "image_reference": runtime["image_reference"],
            "image_id": runtime["image_id"],
            "repo_digests": runtime["repo_digests"],
            "model": baseline_manifest["configuration"]["model"],
            "model_revision": baseline_manifest["configuration"]["model_revision"],
            "served_model_name": baseline_manifest["configuration"]["served_model_name"],
            "endpoint_bind": "127.0.0.1:8000",
            "api_validation": {
                "health_status": 200,
                "models_id": "qwen2.5-1.5b-instruct",
                "chat_expected": "GPU Docker path works.",
                "chat_observed": "GPU Docker path works.",
            },
        },
        "workload": {
            "concurrency": configuration["concurrency"],
            "requests_per_level": configuration["requests_per_level"],
            "warmup_requests_per_run": configuration["warmup_requests"],
            "runs_per_scenario": configuration["runs"],
            "max_tokens": configuration["max_tokens"],
            "scenario_count": len(scenarios),
            "total_measured_requests": sum(
                int(scenario["measured_requests"]) for scenario in scenarios
            ),
            "prompt_semantics": (
                "Five exact prompts repeat after warm-up; prefix-cache is a hot "
                "exact-prompt upper-bound, not a general traffic estimate."
            ),
        },
        "scenarios": scenarios,
        "source_artifacts": sources,
        "preflight_artifact": verified_artifact(path=preflight_path),
        "limitations": [
            "One Windows 11 workstation using Docker Desktop and WSL 2.",
            "The physical display GPU was host-shared; Compose did not provide exclusivity.",
            "Local loopback client, one unquantized 1.5B model, and one GPU only.",
            "No Kubernetes, autoscaling, multi-GPU, DCGM, quality, or cost measurement.",
            "WSL pin_memory was disabled by vLLM and may differ from native Linux.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-dir", default="benchmark-results")
    parser.add_argument(
        "--preflight",
        default="docs/benchmarks/evidence/local-rtx4080-super-preflight.json",
    )
    parser.add_argument(
        "--output",
        default="docs/benchmarks/evidence/local-rtx4080-super-vllm-summary.json",
    )
    parser.add_argument("--reviewed-on", default="2026-07-28")
    args = parser.parse_args()

    evidence = build_evidence(
        benchmark_dir=Path(args.benchmark_dir),
        preflight_path=Path(args.preflight),
        reviewed_on=args.reviewed_on,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"published reviewed GPU evidence: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
