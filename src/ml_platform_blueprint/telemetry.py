"""In-process metrics exported in Prometheus text format."""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass, field


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(**values: str | int) -> str:
    rendered = ",".join(
        f'{key}="{_escape_label(str(value))}"' for key, value in sorted(values.items())
    )
    return "{" + rendered + "}"


@dataclass(slots=True)
class Telemetry:
    """Thread-safe counters sufficient for local and Kubernetes demos."""

    training_runs: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    promotions: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    predictions: Counter[tuple[str, str, int, str]] = field(default_factory=Counter)
    routing: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    prediction_latency_sum: dict[tuple[str, str, int], float] = field(default_factory=dict)
    prediction_latency_count: Counter[tuple[str, str, int]] = field(default_factory=Counter)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_training(self, tenant: str, model_name: str, status: str) -> None:
        with self._lock:
            self.training_runs[(tenant, model_name, status)] += 1

    def record_promotion(self, tenant: str, model_name: str, outcome: str) -> None:
        with self._lock:
            self.promotions[(tenant, model_name, outcome)] += 1

    def record_prediction(
        self,
        tenant: str,
        model_name: str,
        version: int,
        route: str,
        outcome: str,
        duration_seconds: float,
    ) -> None:
        with self._lock:
            self.predictions[(tenant, model_name, version, outcome)] += 1
            self.routing[(tenant, model_name, route)] += 1
            latency_key = (tenant, model_name, version)
            self.prediction_latency_sum[latency_key] = (
                self.prediction_latency_sum.get(latency_key, 0.0) + duration_seconds
            )
            self.prediction_latency_count[(tenant, model_name, version)] += 1

    def render(self) -> str:
        lines = [
            "# HELP ml_platform_training_runs_total Completed training pipeline runs.",
            "# TYPE ml_platform_training_runs_total counter",
        ]
        with self._lock:
            for (tenant, model, status), count in sorted(self.training_runs.items()):
                lines.append(
                    "ml_platform_training_runs_total"
                    f"{_labels(tenant=tenant, model=model, status=status)} {count}"
                )
            lines.extend(
                [
                    "# HELP ml_platform_promotion_decisions_total Promotion decisions.",
                    "# TYPE ml_platform_promotion_decisions_total counter",
                ]
            )
            for (tenant, model, outcome), count in sorted(self.promotions.items()):
                lines.append(
                    "ml_platform_promotion_decisions_total"
                    f"{_labels(tenant=tenant, model=model, outcome=outcome)} {count}"
                )
            lines.extend(
                [
                    "# HELP ml_platform_predictions_total Prediction requests.",
                    "# TYPE ml_platform_predictions_total counter",
                ]
            )
            for (tenant, model, version, outcome), count in sorted(self.predictions.items()):
                lines.append(
                    "ml_platform_predictions_total"
                    f"{_labels(tenant=tenant, model=model, version=version, outcome=outcome)} "
                    f"{count}"
                )
            lines.extend(
                [
                    "# HELP ml_platform_routed_requests_total Stable/canary routing decisions.",
                    "# TYPE ml_platform_routed_requests_total counter",
                ]
            )
            for (tenant, model, route), count in sorted(self.routing.items()):
                lines.append(
                    "ml_platform_routed_requests_total"
                    f"{_labels(tenant=tenant, model=model, route=route)} {count}"
                )
            lines.extend(
                [
                    "# HELP ml_platform_prediction_duration_seconds "
                    "Accumulated prediction duration.",
                    "# TYPE ml_platform_prediction_duration_seconds summary",
                ]
            )
            for key, duration_sum in sorted(self.prediction_latency_sum.items()):
                tenant, model, version = key
                label_text = _labels(tenant=tenant, model=model, version=version)
                lines.append(
                    f"ml_platform_prediction_duration_seconds_sum{label_text} {duration_sum:.9f}"
                )
                lines.append(
                    f"ml_platform_prediction_duration_seconds_count{label_text} "
                    f"{self.prediction_latency_count[key]}"
                )
        lines.append("")
        return "\n".join(lines)
