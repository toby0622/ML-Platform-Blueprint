"""Translate benchmark throughput into explicit capacity and cost estimates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def calculate(assumptions: dict[str, float]) -> dict[str, float]:
    gpu_hourly_cost = assumptions["gpu_hourly_cost_usd"]
    output_tps = assumptions["output_tokens_per_second"]
    utilization = assumptions["target_utilization"]
    average_output_tokens = assumptions["average_output_tokens_per_request"]
    replicas = assumptions["replicas"]

    if (
        gpu_hourly_cost <= 0
        or output_tps <= 0
        or not 0 < utilization <= 1
        or average_output_tokens <= 0
        or replicas < 1
        or not float(replicas).is_integer()
    ):
        raise ValueError(
            "cost and throughput must be positive, utilization must be in (0, 1], "
            "and replicas must be a positive integer"
        )

    effective_tokens_per_hour_per_replica = output_tps * 3600 * utilization
    fleet_tokens_per_hour = effective_tokens_per_hour_per_replica * replicas
    fleet_hourly_cost = gpu_hourly_cost * replicas
    cost_per_million_tokens = fleet_hourly_cost * 1_000_000 / max(fleet_tokens_per_hour, 1e-9)
    requests_per_hour = fleet_tokens_per_hour / max(average_output_tokens, 1e-9)
    return {
        "effective_tokens_per_hour_per_replica": effective_tokens_per_hour_per_replica,
        "fleet_tokens_per_hour": fleet_tokens_per_hour,
        "fleet_hourly_cost_usd": fleet_hourly_cost,
        "estimated_requests_per_hour": requests_per_hour,
        "cost_per_request_usd": fleet_hourly_cost / max(requests_per_hour, 1e-9),
        "cost_per_million_output_tokens_usd": cost_per_million_tokens,
        "monthly_always_on_cost_usd": fleet_hourly_cost * 730,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate inference capacity cost.")
    parser.add_argument("--assumptions", default="benchmarks/cost/assumptions.json")
    parser.add_argument("--output", default="benchmark-results/cost.json")
    args = parser.parse_args()

    assumptions = json.loads(Path(args.assumptions).read_text(encoding="utf-8"))
    result: dict[str, Any] = {
        "schema_version": "1",
        "assumptions": assumptions,
        "estimates": calculate(assumptions),
        "warning": (
            "Planning estimate only. Validate cloud price, utilization, token mix, "
            "quality, and benchmark variance before making a capacity decision."
        ),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
