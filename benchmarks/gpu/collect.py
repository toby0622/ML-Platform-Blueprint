"""Collect schema-versioned NVIDIA GPU telemetry with ``nvidia-smi``."""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"
QUERY_FIELDS = (
    "timestamp",
    "index",
    "name",
    "uuid",
    "driver_version",
    "memory.total",
    "memory.used",
    "utilization.gpu",
    "utilization.memory",
    "temperature.gpu",
    "power.draw",
    "power.limit",
)
SUMMARY_METRICS = (
    "memory_total_mib",
    "memory_used_mib",
    "gpu_utilization_percent",
    "memory_utilization_percent",
    "temperature_celsius",
    "power_draw_watts",
    "power_limit_watts",
)
MISSING_VALUES = frozenset(
    {
        "",
        "n/a",
        "[n/a]",
        "not supported",
        "[not supported]",
        "unknown error",
        "[unknown error]",
    }
)


@dataclass(frozen=True, slots=True)
class GpuSample:
    """One row returned by a single ``nvidia-smi`` query."""

    timestamp: str | None
    index: int | None
    name: str | None
    uuid: str | None
    driver_version: str | None
    memory_total_mib: float | None
    memory_used_mib: float | None
    gpu_utilization_percent: float | None
    memory_utilization_percent: float | None
    temperature_celsius: float | None
    power_draw_watts: float | None
    power_limit_watts: float | None


def _optional_text(value: str) -> str | None:
    normalized = value.strip()
    return None if normalized.casefold() in MISSING_VALUES else normalized


def _optional_float(value: str, *, field: str, row_number: int) -> float | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    try:
        return float(normalized)
    except ValueError as error:
        raise ValueError(
            f"invalid numeric value for {field!r} in nvidia-smi row {row_number}: {normalized!r}"
        ) from error


def _optional_int(value: str, *, field: str, row_number: int) -> int | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    try:
        return int(normalized)
    except ValueError as error:
        raise ValueError(
            f"invalid integer value for {field!r} in nvidia-smi row {row_number}: {normalized!r}"
        ) from error


def parse_nvidia_smi_csv(output: str) -> list[GpuSample]:
    """Parse the exact no-header, no-units query format used by this collector."""

    samples: list[GpuSample] = []
    for row_number, row in enumerate(csv.reader(output.splitlines(), skipinitialspace=True), 1):
        if not row or all(not value.strip() for value in row):
            continue
        if len(row) != len(QUERY_FIELDS):
            raise ValueError(
                f"nvidia-smi row {row_number} has {len(row)} columns; expected {len(QUERY_FIELDS)}"
            )
        samples.append(
            GpuSample(
                timestamp=_optional_text(row[0]),
                index=_optional_int(row[1], field="index", row_number=row_number),
                name=_optional_text(row[2]),
                uuid=_optional_text(row[3]),
                driver_version=_optional_text(row[4]),
                memory_total_mib=_optional_float(
                    row[5],
                    field="memory.total",
                    row_number=row_number,
                ),
                memory_used_mib=_optional_float(
                    row[6],
                    field="memory.used",
                    row_number=row_number,
                ),
                gpu_utilization_percent=_optional_float(
                    row[7],
                    field="utilization.gpu",
                    row_number=row_number,
                ),
                memory_utilization_percent=_optional_float(
                    row[8],
                    field="utilization.memory",
                    row_number=row_number,
                ),
                temperature_celsius=_optional_float(
                    row[9],
                    field="temperature.gpu",
                    row_number=row_number,
                ),
                power_draw_watts=_optional_float(
                    row[10],
                    field="power.draw",
                    row_number=row_number,
                ),
                power_limit_watts=_optional_float(
                    row[11],
                    field="power.limit",
                    row_number=row_number,
                ),
            )
        )
    return samples


def query_nvidia_smi(
    *,
    executable: str = "nvidia-smi",
    timeout_seconds: float = 10.0,
) -> list[GpuSample]:
    """Run one telemetry query without invoking a command shell."""

    command = [
        executable,
        f"--query-gpu={','.join(QUERY_FIELDS)}",
        "--format=csv,noheader,nounits",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=timeout_seconds,
        shell=False,
    )
    samples = parse_nvidia_smi_csv(completed.stdout)
    if not samples:
        raise RuntimeError("nvidia-smi returned no GPU telemetry rows")
    return samples


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _summarize_metric(values: list[float]) -> dict[str, int | float | None]:
    return {
        "count": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": max(values) if values else None,
    }


def _gpu_identity(sample: GpuSample) -> tuple[str | None, int | None, str | None]:
    return sample.uuid, sample.index, sample.name


def summarize(samples: list[GpuSample]) -> dict[str, Any]:
    """Summarize observed values per physical GPU without filling missing data."""

    grouped: dict[tuple[str | None, int | None, str | None], list[GpuSample]] = {}
    for sample in samples:
        grouped.setdefault(_gpu_identity(sample), []).append(sample)

    per_gpu: list[dict[str, Any]] = []
    for (uuid, index, name), gpu_samples in sorted(
        grouped.items(),
        key=lambda item: (
            item[0][1] is None,
            item[0][1] if item[0][1] is not None else 0,
            item[0][0] or "",
            item[0][2] or "",
        ),
    ):
        driver_versions = sorted(
            {sample.driver_version for sample in gpu_samples if sample.driver_version is not None}
        )
        metrics = {
            metric: _summarize_metric(
                [value for sample in gpu_samples if (value := getattr(sample, metric)) is not None]
            )
            for metric in SUMMARY_METRICS
        }
        per_gpu.append(
            {
                "identity": {
                    "index": index,
                    "name": name,
                    "uuid": uuid,
                    "driver_versions_observed": driver_versions,
                },
                "sample_count": len(gpu_samples),
                "metrics": metrics,
            }
        )

    return {
        "gpu_count_observed": len(per_gpu),
        "sample_count": len(samples),
        "per_gpu": per_gpu,
    }


def collect_samples(
    *,
    duration_seconds: float,
    interval_seconds: float,
    query: Callable[[], list[GpuSample]],
) -> tuple[list[GpuSample], int]:
    """Collect immediately, then repeat at the requested interval until the deadline."""

    if duration_seconds < 0:
        raise ValueError("duration_seconds must be non-negative")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")

    started = time.monotonic()
    deadline = started + duration_seconds
    samples: list[GpuSample] = []
    query_count = 0
    while True:
        samples.extend(query())
        query_count += 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval_seconds, remaining))
    return samples, query_count


def build_report(
    *,
    samples: list[GpuSample],
    requested_duration_seconds: float,
    requested_interval_seconds: float,
    query_count: int,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    """Build the stable JSON document written by the command-line collector."""

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "nvidia-gpu-telemetry",
        "collection": {
            "source": "nvidia-smi",
            "query_fields": list(QUERY_FIELDS),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "requested_duration_seconds": requested_duration_seconds,
            "requested_interval_seconds": requested_interval_seconds,
            "query_count": query_count,
        },
        "summary": summarize(samples),
        "samples": [asdict(sample) for sample in samples],
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    """Write telemetry as deterministic, human-readable JSON."""

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect NVIDIA GPU telemetry for benchmark evidence."
    )
    parser.add_argument("--duration", type=_non_negative_float, default=60.0)
    parser.add_argument("--interval", type=_positive_float, default=1.0)
    parser.add_argument("--query-timeout", type=_positive_float, default=10.0)
    parser.add_argument("--nvidia-smi", default="nvidia-smi")
    parser.add_argument("--output", default="benchmark-results/gpu-telemetry.json")
    args = parser.parse_args()

    started_at = datetime.now(UTC)
    samples, query_count = collect_samples(
        duration_seconds=args.duration,
        interval_seconds=args.interval,
        query=lambda: query_nvidia_smi(
            executable=args.nvidia_smi,
            timeout_seconds=args.query_timeout,
        ),
    )
    finished_at = datetime.now(UTC)
    report = build_report(
        samples=samples,
        requested_duration_seconds=args.duration,
        requested_interval_seconds=args.interval,
        query_count=query_count,
        started_at=started_at,
        finished_at=finished_at,
    )
    output = Path(args.output)
    write_report(report, output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
