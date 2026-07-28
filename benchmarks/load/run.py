"""Dependency-free concurrent load test for the reference prediction API."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Sample:
    latency_ms: float
    status: int
    route: str
    version: str
    error: str | None = None


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(samples: list[Sample], elapsed_seconds: float) -> dict[str, Any]:
    latencies = [sample.latency_ms for sample in samples]
    successes = [sample for sample in samples if 200 <= sample.status < 300]
    return {
        "requests": len(samples),
        "successful_requests": len(successes),
        "failed_requests": len(samples) - len(successes),
        "availability": len(successes) / max(1, len(samples)),
        "error_rate": (len(samples) - len(successes)) / max(1, len(samples)),
        "throughput_rps": len(samples) / max(elapsed_seconds, 1e-9),
        "latency_ms": {
            "mean": statistics.fmean(latencies) if latencies else 0.0,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": max(latencies, default=0.0),
        },
        "routes": dict(Counter(sample.route for sample in successes)),
        "versions": dict(Counter(sample.version for sample in successes)),
        "status_codes": dict(Counter(str(sample.status) for sample in samples)),
        "errors": dict(Counter(sample.error for sample in samples if sample.error is not None)),
    }


def send_request(
    *,
    endpoint: str,
    tenant: str,
    payload: bytes,
    request_number: int,
    timeout: float,
) -> Sample:
    request = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Tenant-Id": tenant,
            "X-Request-Id": f"load-{request_number}",
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
            return Sample(
                latency_ms=(time.perf_counter() - started) * 1000,
                status=response.status,
                route=str(body.get("route", "unknown")),
                version=str(body.get("model_version", "unknown")),
            )
    except urllib.error.HTTPError as error:
        return Sample(
            latency_ms=(time.perf_counter() - started) * 1000,
            status=error.code,
            route="error",
            version="unknown",
            error=f"HTTP {error.code}",
        )
    except (OSError, TimeoutError) as error:
        return Sample(
            latency_ms=(time.perf_counter() - started) * 1000,
            status=0,
            route="error",
            version="unknown",
            error=type(error).__name__,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Load-test model prediction.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--tenant", default="team-a")
    parser.add_argument("--model", default="churn-classifier")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--output", default="benchmark-results/load.json")
    args = parser.parse_args()

    instance = {
        "tenure_months": 12.0,
        "monthly_spend": 90.0,
        "support_tickets": 2.0,
        "usage_score": 55.0,
        "payment_failures": 1.0,
        "contract_months": 1.0,
    }
    payload = json.dumps({"instances": [instance]}).encode()
    endpoint = f"{args.base_url.rstrip('/')}/v1/tenants/{args.tenant}/models/{args.model}/predict"
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        samples = list(
            executor.map(
                lambda index: send_request(
                    endpoint=endpoint,
                    tenant=args.tenant,
                    payload=payload,
                    request_number=index,
                    timeout=args.timeout,
                ),
                range(args.requests),
            )
        )
    elapsed = time.perf_counter() - started
    result = {
        "schema_version": "1",
        "configuration": {
            "endpoint": endpoint,
            "requests": args.requests,
            "concurrency": args.concurrency,
            "timeout_seconds": args.timeout,
        },
        "elapsed_seconds": elapsed,
        "summary": summarize(samples, elapsed),
        "samples": [asdict(sample) for sample in samples],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0 if result["summary"]["error_rate"] <= args.max_error_rate else 2


if __name__ == "__main__":
    raise SystemExit(main())
