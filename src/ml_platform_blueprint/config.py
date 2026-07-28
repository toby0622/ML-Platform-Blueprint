"""Environment-driven application configuration."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def _discover_revision() -> str:
    configured = os.getenv("ML_PLATFORM_CODE_REVISION")
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _otel_traces_endpoint() -> str | None:
    traces_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if traces_endpoint:
        return traces_endpoint
    general_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if general_endpoint:
        return f"{general_endpoint.rstrip('/')}/v1/traces"
    return None


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings shared by the API and CLI."""

    state_dir: Path = field(default_factory=lambda: Path(".ml-platform"))
    allowed_tenants: tuple[str, ...] = ("team-a", "team-b")
    code_revision: str = field(default_factory=_discover_revision)
    mlflow_tracking_uri: str | None = None
    mlflow_experiment: str = "ml-platform-blueprint"
    environment: str = "local"
    otel_traces_endpoint: str | None = None
    otel_service_name: str = "ml-platform-control-plane"

    @classmethod
    def from_env(cls) -> Settings:
        tenants = tuple(
            tenant.strip()
            for tenant in os.getenv("ML_PLATFORM_TENANTS", "team-a,team-b").split(",")
            if tenant.strip()
        )
        return cls(
            state_dir=Path(os.getenv("ML_PLATFORM_STATE_DIR", ".ml-platform")),
            allowed_tenants=tenants,
            code_revision=_discover_revision(),
            mlflow_tracking_uri=os.getenv("MLFLOW_TRACKING_URI") or None,
            mlflow_experiment=os.getenv("MLFLOW_EXPERIMENT_NAME", "ml-platform-blueprint"),
            environment=os.getenv("ML_PLATFORM_ENVIRONMENT", "local"),
            otel_traces_endpoint=_otel_traces_endpoint(),
            otel_service_name=os.getenv(
                "OTEL_SERVICE_NAME",
                "ml-platform-control-plane",
            ),
        )
