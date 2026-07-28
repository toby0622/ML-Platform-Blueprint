from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
from benchmarks.gpu.collect import (
    QUERY_FIELDS,
    GpuSample,
    build_report,
    collect_samples,
    parse_nvidia_smi_csv,
    query_nvidia_smi,
    summarize,
    write_report,
)


def sample(**overrides: object) -> GpuSample:
    values: dict[str, object] = {
        "timestamp": "2026/07/28 20:00:00.000",
        "index": 0,
        "name": "NVIDIA GeForce RTX 4080 SUPER",
        "uuid": "GPU-test",
        "driver_version": "610.74",
        "memory_total_mib": 16376.0,
        "memory_used_mib": 2048.0,
        "gpu_utilization_percent": 25.0,
        "memory_utilization_percent": 10.0,
        "temperature_celsius": 45.0,
        "power_draw_watts": 80.0,
        "power_limit_watts": 320.0,
    }
    values.update(overrides)
    return GpuSample(**values)  # type: ignore[arg-type]


def test_parse_nvidia_smi_csv_preserves_values_and_missing_data() -> None:
    output = (
        "2026/07/28 20:00:00.000, 0, NVIDIA GeForce RTX 4080 SUPER, GPU-one, "
        "610.74, 16376, 2251, 32, 12, 49, 56.50, 320.00\n"
        "2026/07/28 20:00:00.000, 1, NVIDIA Test GPU, GPU-two, "
        "610.74, 8192, N/A, [Not Supported], 0, N/A, [N/A], 200.00\n"
    )

    samples = parse_nvidia_smi_csv(output)

    assert len(samples) == 2
    assert samples[0].name == "NVIDIA GeForce RTX 4080 SUPER"
    assert samples[0].memory_total_mib == 16376.0
    assert samples[0].power_draw_watts == 56.5
    assert samples[1].memory_used_mib is None
    assert samples[1].gpu_utilization_percent is None
    assert samples[1].temperature_celsius is None
    assert samples[1].power_draw_watts is None


def test_parse_rejects_malformed_or_non_numeric_rows() -> None:
    with pytest.raises(ValueError, match="expected 12"):
        parse_nvidia_smi_csv("only, two")

    invalid_numeric = (
        "2026/07/28 20:00:00.000, 0, NVIDIA GPU, GPU-one, 610.74, sixteen-gib, 0, 0, 0, 40, 20, 320"
    )
    with pytest.raises(ValueError, match=r"memory\.total"):
        parse_nvidia_smi_csv(invalid_numeric)


def test_query_uses_argument_list_without_a_shell() -> None:
    output = (
        "2026/07/28 20:00:00.000, 0, NVIDIA GPU, GPU-one, 610.74, 16376, 1, 0, 0, 40, 20, 320\n"
    )
    completed = CompletedProcess(args=[], returncode=0, stdout=output, stderr="")

    with patch("benchmarks.gpu.collect.subprocess.run", return_value=completed) as run:
        samples = query_nvidia_smi(
            executable="C:/Program Files/NVIDIA Corporation/NVSMI/nvidia-smi.exe",
            timeout_seconds=3.0,
        )

    assert samples[0].uuid == "GPU-one"
    run.assert_called_once_with(
        [
            "C:/Program Files/NVIDIA Corporation/NVSMI/nvidia-smi.exe",
            f"--query-gpu={','.join(QUERY_FIELDS)}",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=3.0,
        shell=False,
    )


def test_summarize_calculates_per_gpu_percentiles_and_keeps_nulls() -> None:
    samples = [
        sample(gpu_utilization_percent=value, power_draw_watts=None)
        for value in (0.0, 10.0, 20.0, 100.0)
    ]
    samples.append(
        sample(
            index=1,
            uuid="GPU-second",
            name="Second GPU",
            gpu_utilization_percent=50.0,
            power_draw_watts=75.0,
        )
    )

    summary = summarize(samples)

    assert summary["gpu_count_observed"] == 2
    assert summary["sample_count"] == 5
    first_gpu = summary["per_gpu"][0]
    utilization = first_gpu["metrics"]["gpu_utilization_percent"]
    assert utilization["count"] == 4
    assert utilization["p50"] == 15.0
    assert utilization["p95"] == pytest.approx(88.0)
    assert utilization["max"] == 100.0
    assert first_gpu["metrics"]["power_draw_watts"] == {
        "count": 0,
        "p50": None,
        "p95": None,
        "max": None,
    }


def test_collect_once_and_write_schema_versioned_report(tmp_path: Path) -> None:
    observations = [sample()]
    samples, query_count = collect_samples(
        duration_seconds=0,
        interval_seconds=1,
        query=lambda: observations,
    )
    observed_at = datetime(2026, 7, 28, 12, tzinfo=UTC)
    report = build_report(
        samples=samples,
        requested_duration_seconds=0,
        requested_interval_seconds=1,
        query_count=query_count,
        started_at=observed_at,
        finished_at=observed_at,
    )
    output = tmp_path / "gpu.json"

    write_report(report, output)
    written = json.loads(output.read_text(encoding="utf-8"))

    assert query_count == 1
    assert written["schema_version"] == "1"
    assert written["kind"] == "nvidia-gpu-telemetry"
    assert written["collection"]["source"] == "nvidia-smi"
    assert written["summary"]["sample_count"] == 1
    assert written["samples"][0]["memory_total_mib"] == 16376.0
