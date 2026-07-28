"""Reproducible OpenAI-compatible streaming benchmark for vLLM."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml


@dataclass(frozen=True, slots=True)
class LlmSample:
    run_number: int
    concurrency: int
    prompt_id: int
    success: bool
    ttft_ms: float
    end_to_end_ms: float
    mean_itl_ms: float
    prompt_tokens: int
    completion_tokens: int
    error: str | None


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def run_stream(
    *,
    client: httpx.Client,
    endpoint: str,
    model: str,
    prompt: str,
    prompt_id: int,
    run_number: int,
    concurrency: int,
    max_tokens: int,
) -> LlmSample:
    started = time.perf_counter()
    first_token_at: float | None = None
    token_times: list[float] = []
    prompt_tokens = 0
    completion_tokens = 0
    try:
        with client.stream(
            "POST",
            endpoint,
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                event = json.loads(line[6:])
                usage = event.get("usage")
                if usage:
                    prompt_tokens = int(usage.get("prompt_tokens", 0))
                    completion_tokens = int(usage.get("completion_tokens", 0))
                choices = event.get("choices", [])
                if choices and choices[0].get("delta", {}).get("content"):
                    now = time.perf_counter()
                    first_token_at = first_token_at or now
                    token_times.append(now)
        ended = time.perf_counter()
        if completion_tokens == 0:
            completion_tokens = len(token_times)
        if first_token_at is None or completion_tokens == 0:
            return LlmSample(
                run_number=run_number,
                concurrency=concurrency,
                prompt_id=prompt_id,
                success=False,
                ttft_ms=0,
                end_to_end_ms=(ended - started) * 1000,
                mean_itl_ms=0,
                prompt_tokens=prompt_tokens,
                completion_tokens=0,
                error="EmptyCompletion",
            )
        token_finished_at = token_times[-1] if len(token_times) > 1 else ended
        mean_itl_ms = (
            (token_finished_at - first_token_at) * 1000 / (completion_tokens - 1)
            if completion_tokens > 1
            else 0.0
        )
        return LlmSample(
            run_number=run_number,
            concurrency=concurrency,
            prompt_id=prompt_id,
            success=True,
            ttft_ms=(first_token_at - started) * 1000,
            end_to_end_ms=(ended - started) * 1000,
            mean_itl_ms=mean_itl_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            error=None,
        )
    except (httpx.HTTPError, json.JSONDecodeError) as error:
        return LlmSample(
            run_number=run_number,
            concurrency=concurrency,
            prompt_id=prompt_id,
            success=False,
            ttft_ms=0,
            end_to_end_ms=(time.perf_counter() - started) * 1000,
            mean_itl_ms=0,
            prompt_tokens=0,
            completion_tokens=0,
            error=type(error).__name__,
        )


def summarize(samples: list[LlmSample], elapsed: float) -> dict[str, Any]:
    successful = [sample for sample in samples if sample.success]
    ttft = [sample.ttft_ms for sample in successful]
    e2e = [sample.end_to_end_ms for sample in successful]
    itl = [sample.mean_itl_ms for sample in successful if sample.mean_itl_ms > 0]
    prompt_tokens = sum(sample.prompt_tokens for sample in successful)
    completion_tokens = sum(sample.completion_tokens for sample in successful)
    return {
        "elapsed_seconds": elapsed,
        "requests": len(samples),
        "successful_requests": len(successful),
        "error_rate": 1 - (len(successful) / max(1, len(samples))),
        "request_throughput_rps": len(successful) / max(elapsed, 1e-9),
        "input_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "output_throughput_tokens_per_second": completion_tokens / max(elapsed, 1e-9),
        "total_throughput_tokens_per_second": (
            (prompt_tokens + completion_tokens) / max(elapsed, 1e-9)
        ),
        "ttft_ms": {
            "p50": _percentile(ttft, 0.50),
            "p95": _percentile(ttft, 0.95),
            "p99": _percentile(ttft, 0.99),
        },
        "end_to_end_ms": {
            "p50": _percentile(e2e, 0.50),
            "p95": _percentile(e2e, 0.95),
            "p99": _percentile(e2e, 0.99),
        },
        "mean_itl_ms": statistics.fmean(itl) if itl else 0.0,
        "errors": dict(Counter(sample.error for sample in samples if sample.error)),
    }


def evaluate_quality_gate(
    *,
    warmup_failures: int,
    aggregate_error_rate: float,
    results_by_concurrency: dict[str, dict[str, Any]],
    results_by_run: list[dict[str, Any]],
    max_error_rate: float,
) -> dict[str, Any]:
    """Require the error budget to hold at every measured concurrency and run."""

    violations: list[dict[str, Any]] = []
    if warmup_failures:
        violations.append(
            {
                "scope": "warmup",
                "failures": warmup_failures,
            }
        )

    def check_error_rate(scope: str, error_rate: float, **labels: Any) -> None:
        if error_rate > max_error_rate:
            violations.append(
                {
                    "scope": scope,
                    **labels,
                    "error_rate": error_rate,
                }
            )

    check_error_rate("aggregate", aggregate_error_rate)
    for concurrency, summary in results_by_concurrency.items():
        check_error_rate(
            "concurrency",
            float(summary["error_rate"]),
            concurrency=int(concurrency),
        )
    for run_result in results_by_run:
        for concurrency, summary in run_result["results_by_concurrency"].items():
            check_error_rate(
                "run_concurrency",
                float(summary["error_rate"]),
                run_number=int(run_result["run_number"]),
                concurrency=int(concurrency),
            )

    return {
        "passed": not violations,
        "max_error_rate": max_error_rate,
        "violations": violations,
    }


def load_scenario(path: Path, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    configuration = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenarios = configuration.get("scenarios", [])
    scenario = next((item for item in scenarios if item.get("name") == name), None)
    if scenario is None:
        available = ", ".join(str(item.get("name")) for item in scenarios)
        raise ValueError(f"unknown scenario {name!r}; available scenarios: {available}")
    return configuration, scenario


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark a vLLM endpoint.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompts", default="benchmarks/inference/prompts.json")
    parser.add_argument("--config", default="benchmarks/inference/configs.yaml")
    parser.add_argument("--scenario", default="baseline")
    parser.add_argument("--concurrency")
    parser.add_argument("--requests-per-level", type=int)
    parser.add_argument("--warmup-requests", type=int)
    parser.add_argument("--runs", type=int)
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--output", default="benchmark-results/vllm.json")
    args = parser.parse_args()

    prompts = json.loads(Path(args.prompts).read_text(encoding="utf-8"))
    if not isinstance(prompts, list) or not prompts:
        raise ValueError("prompts must be a non-empty JSON array")
    configuration, scenario = load_scenario(Path(args.config), args.scenario)
    configured_concurrency = args.concurrency or ",".join(
        str(value) for value in configuration["concurrency"]
    )
    concurrency_levels = [int(value) for value in configured_concurrency.split(",")]
    requests_per_level = (
        args.requests_per_level
        if args.requests_per_level is not None
        else int(configuration["requests_per_level"])
    )
    warmup_requests = (
        args.warmup_requests
        if args.warmup_requests is not None
        else int(configuration["warmup_requests"])
    )
    runs = args.runs if args.runs is not None else int(configuration["runs_per_scenario"])
    max_tokens = (
        args.max_tokens if args.max_tokens is not None else int(configuration["max_tokens"])
    )
    if (
        any(level < 1 for level in concurrency_levels)
        or requests_per_level < 1
        or warmup_requests < 0
        or runs < 1
        or max_tokens < 1
        or not 0 <= args.max_error_rate <= 1
    ):
        raise ValueError("benchmark counts must be positive and max-error-rate must be in [0, 1]")

    all_samples: list[LlmSample] = []
    samples_by_concurrency: dict[int, list[LlmSample]] = {
        concurrency: [] for concurrency in concurrency_levels
    }
    elapsed_by_concurrency = dict.fromkeys(concurrency_levels, 0.0)
    results_by_run: list[dict[str, Any]] = []
    warmup_failures = 0
    endpoint = f"{args.base_url.rstrip('/')}/chat/completions"
    with httpx.Client(timeout=args.timeout) as client:
        for run_number in range(1, runs + 1):
            warmup_samples = [
                run_stream(
                    client=client,
                    endpoint=endpoint,
                    model=args.model,
                    prompt=str(prompts[index % len(prompts)]),
                    prompt_id=index % len(prompts),
                    run_number=run_number,
                    concurrency=1,
                    max_tokens=max_tokens,
                )
                for index in range(warmup_requests)
            ]
            warmup_failures += sum(not sample.success for sample in warmup_samples)
            run_results: dict[str, Any] = {}
            for concurrency in concurrency_levels:
                started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    samples = list(
                        executor.map(
                            lambda index, level=concurrency, run=run_number: run_stream(
                                client=client,
                                endpoint=endpoint,
                                model=args.model,
                                prompt=str(prompts[index % len(prompts)]),
                                prompt_id=index % len(prompts),
                                run_number=run,
                                concurrency=level,
                                max_tokens=max_tokens,
                            ),
                            range(requests_per_level),
                        )
                    )
                elapsed = time.perf_counter() - started
                all_samples.extend(samples)
                samples_by_concurrency[concurrency].extend(samples)
                elapsed_by_concurrency[concurrency] += elapsed
                run_results[str(concurrency)] = summarize(samples, elapsed)
            results_by_run.append(
                {
                    "run_number": run_number,
                    "warmup_failures": sum(not sample.success for sample in warmup_samples),
                    "results_by_concurrency": run_results,
                }
            )

    all_results = {
        str(concurrency): summarize(
            samples_by_concurrency[concurrency],
            elapsed_by_concurrency[concurrency],
        )
        for concurrency in concurrency_levels
    }
    total_failures = sum(not sample.success for sample in all_samples)
    aggregate_error_rate = total_failures / max(1, len(all_samples))
    quality_gate = evaluate_quality_gate(
        warmup_failures=warmup_failures,
        aggregate_error_rate=aggregate_error_rate,
        results_by_concurrency=all_results,
        results_by_run=results_by_run,
        max_error_rate=args.max_error_rate,
    )
    result = {
        "schema_version": "1",
        "configuration": {
            "endpoint": endpoint,
            "model": args.model,
            "profile": configuration.get("profile"),
            "scenario": args.scenario,
            "engine_args": scenario.get("engine_args", {}),
            "concurrency": concurrency_levels,
            "requests_per_level": requests_per_level,
            "warmup_requests": warmup_requests,
            "runs": runs,
            "max_tokens": max_tokens,
        },
        "warmup_failures": warmup_failures,
        "aggregate_error_rate": aggregate_error_rate,
        "quality_gate": quality_gate,
        "results_by_concurrency": all_results,
        "results_by_run": results_by_run,
        "samples": [asdict(sample) for sample in all_samples],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(all_results, indent=2, sort_keys=True))
    return 0 if quality_gate["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
