"""Start a scenario-specific local vLLM service and capture benchmark evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from benchmarks.gpu.collect import GpuSample, build_report, query_nvidia_smi, write_report
from benchmarks.inference.vllm_benchmark import load_scenario

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
DEFAULT_MODEL_REVISION = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
DEFAULT_SERVED_MODEL = "qwen2.5-1.5b-instruct"
SUPPORTED_ENGINE_ARGS = {
    "enable_prefix_caching",
    "gpu_memory_utilization",
    "max_model_len",
    "max_num_batched_tokens",
}
DOTENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def find_docker_executable() -> str | None:
    """Find Docker even when this process predates Docker Desktop installation."""

    discovered = shutil.which("docker")
    if discovered is not None:
        return discovered
    candidates: list[Path] = []
    local_app_data = os.getenv("LOCALAPPDATA")
    program_files = os.getenv("PROGRAMFILES")
    if local_app_data:
        candidates.append(
            Path(local_app_data) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
        )
    if program_files:
        candidates.append(
            Path(program_files) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
        )
    return next((str(candidate) for candidate in candidates if candidate.is_file()), None)


def with_docker_on_path(environment: dict[str, str], docker: str) -> dict[str, str]:
    """Ensure Docker can launch bundled helpers when the parent process PATH is stale."""

    updated = environment.copy()
    docker_directory = str(Path(docker).resolve().parent)
    path_entries = updated.get("PATH", "").split(os.pathsep)
    if docker_directory.casefold() not in {entry.casefold() for entry in path_entries if entry}:
        updated["PATH"] = os.pathsep.join((docker_directory, *path_entries))
    return updated


def scenario_environment(scenario: dict[str, Any]) -> dict[str, str]:
    """Translate versioned benchmark engine arguments into Compose variables."""

    engine_args = scenario.get("engine_args")
    if not isinstance(engine_args, dict):
        raise ValueError("scenario engine_args must be a mapping")
    unknown = set(engine_args) - SUPPORTED_ENGINE_ARGS
    if unknown:
        names = ", ".join(sorted(str(name) for name in unknown))
        raise ValueError(f"unsupported local vLLM engine args: {names}")

    required = {
        "enable_prefix_caching",
        "gpu_memory_utilization",
        "max_model_len",
    }
    missing = required - set(engine_args)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"local vLLM scenario is missing engine args: {names}")
    prefix_caching = engine_args["enable_prefix_caching"]
    if not isinstance(prefix_caching, bool):
        raise ValueError("enable_prefix_caching must be a boolean")

    return {
        "VLLM_ENABLE_PREFIX_CACHING": str(prefix_caching).lower(),
        "VLLM_GPU_MEMORY_UTILIZATION": str(engine_args["gpu_memory_utilization"]),
        "VLLM_MAX_MODEL_LEN": str(engine_args["max_model_len"]),
        "VLLM_MAX_NUM_BATCHED_TOKENS": str(engine_args.get("max_num_batched_tokens", "")),
    }


def resolve_model_revision(
    *,
    model: str,
    explicit_model: str | None,
    explicit_revision: str | None,
    environment: dict[str, str],
) -> str:
    """Avoid carrying a revision for one repository into an explicit model override."""

    if explicit_revision is not None:
        return explicit_revision
    default_revision = DEFAULT_MODEL_REVISION if model == DEFAULT_MODEL else ""
    if explicit_model is not None:
        return default_revision
    return environment.get("VLLM_MODEL_REVISION", default_revision)


def load_vllm_environment(path: Path) -> dict[str, str]:
    """Load only non-secret vLLM variables from a simple Compose env file."""

    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip()
        if not DOTENV_KEY.fullmatch(key):
            raise ValueError(f"{path}:{line_number}: invalid environment variable name")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key.startswith("VLLM_"):
            values[key] = value
    return values


def _run_checked(
    command: Sequence[str],
    *,
    environment: dict[str, str],
) -> None:
    subprocess.run(
        list(command),
        check=True,
        env=environment,
        shell=False,
    )


def _capture_checked(
    command: Sequence[str],
    *,
    environment: dict[str, str],
) -> str:
    completed = subprocess.run(
        list(command),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        shell=False,
    )
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact_entry(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _sha256(path) if path.is_file() else None,
    }


def inspect_runtime(
    *,
    docker: str,
    compose: Sequence[str],
    environment: dict[str, str],
    image_reference: str,
) -> dict[str, Any]:
    """Capture immutable container and image identities without reading secrets."""

    container_id = _capture_checked(
        [*compose, "ps", "--quiet", "vllm"],
        environment=environment,
    )
    if not container_id:
        raise RuntimeError("Docker Compose did not return a vLLM container ID")
    image_id = _capture_checked(
        [docker, "inspect", "--format", "{{.Image}}", container_id],
        environment=environment,
    )
    raw_repo_digests = _capture_checked(
        [docker, "image", "inspect", "--format", "{{json .RepoDigests}}", image_id],
        environment=environment,
    )
    try:
        parsed_repo_digests = json.loads(raw_repo_digests)
    except json.JSONDecodeError:
        parsed_repo_digests = []
    repo_digests = (
        sorted(str(value) for value in parsed_repo_digests)
        if isinstance(parsed_repo_digests, list)
        else []
    )
    return {
        "container_id": container_id,
        "image_id": image_id,
        "image_reference": image_reference,
        "repo_digests": repo_digests,
    }


def _wait_until_healthy(url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "endpoint has not responded"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 300:
                    return
                last_error = f"health endpoint returned HTTP {response.status}"
        except (OSError, urllib.error.URLError) as error:
            last_error = str(error)
        time.sleep(2)
    raise TimeoutError(f"vLLM did not become healthy within {timeout_seconds:g}s: {last_error}")


class TelemetrySession:
    """Collect host-side GPU samples until the benchmark completes."""

    def __init__(
        self,
        *,
        interval_seconds: float,
        query: Callable[[], list[GpuSample]] = query_nvidia_smi,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("telemetry interval must be positive")
        self.interval_seconds = interval_seconds
        self.query = query
        self.samples: list[GpuSample] = []
        self.query_count = 0
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.error: BaseException | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._collect, name="gpu-telemetry", daemon=True)

    def _collect(self) -> None:
        try:
            while not self._stop.is_set():
                self.samples.extend(self.query())
                self.query_count += 1
                self._stop.wait(self.interval_seconds)
        except BaseException as error:
            self.error = error
            self._stop.set()

    def start(self) -> None:
        self.started_at = datetime.now(UTC)
        self._thread.start()

    def stop_and_write(self, output: Path) -> None:
        self._stop.set()
        self._thread.join(timeout=max(10.0, self.interval_seconds * 2))
        self.finished_at = datetime.now(UTC)
        if self._thread.is_alive():
            raise RuntimeError("GPU telemetry worker did not stop")
        if self.error is not None:
            raise RuntimeError(f"GPU telemetry collection failed: {self.error}") from self.error
        if self.started_at is None or not self.samples:
            raise RuntimeError("GPU telemetry collection produced no samples")
        report = build_report(
            samples=self.samples,
            requested_duration_seconds=(self.finished_at - self.started_at).total_seconds(),
            requested_interval_seconds=self.interval_seconds,
            query_count=self.query_count,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )
        write_report(report, output)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start local vLLM for one scenario and optionally run the benchmark."
    )
    parser.add_argument("--scenario", default="baseline")
    parser.add_argument(
        "--config",
        default="benchmarks/inference/configs-rtx4080-super.yaml",
    )
    parser.add_argument("--prompts", default="benchmarks/inference/prompts.json")
    parser.add_argument("--compose-file", default="compose.gpu.yaml")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model")
    parser.add_argument("--model-revision")
    parser.add_argument("--served-model-name")
    parser.add_argument("--quantization")
    parser.add_argument("--port", type=int)
    parser.add_argument("--startup-timeout", type=float, default=900)
    parser.add_argument("--telemetry-interval", type=float, default=1.0)
    parser.add_argument("--start-only", action="store_true")
    parser.add_argument("--requests-per-level", type=int)
    parser.add_argument("--runs", type=int)
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--output")
    parser.add_argument("--telemetry-output")
    parser.add_argument("--manifest-output")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = _build_parser().parse_args(arguments)
    if options.startup_timeout <= 0:
        raise ValueError("startup timeout must be positive")
    if options.telemetry_interval <= 0:
        raise ValueError("telemetry interval must be positive")
    docker = find_docker_executable()
    if docker is None:
        raise RuntimeError("docker was not found; run `python scripts/gpu_preflight.py`")

    env_file = Path(options.env_file)
    if options.env_file != ".env" and not env_file.is_file():
        raise FileNotFoundError(f"environment file does not exist: {env_file}")
    file_environment = load_vllm_environment(env_file)
    environment = with_docker_on_path(os.environ.copy(), docker)
    for key, value in file_environment.items():
        environment.setdefault(key, value)

    def resolve(name: str, explicit: str | int | None, default: str) -> str:
        return str(explicit) if explicit is not None else environment.get(name, default)

    model = resolve("VLLM_MODEL", options.model, DEFAULT_MODEL)
    model_revision = resolve_model_revision(
        model=model,
        explicit_model=options.model,
        explicit_revision=options.model_revision,
        environment=environment,
    )
    served_model_name = resolve(
        "VLLM_SERVED_MODEL_NAME",
        options.served_model_name,
        DEFAULT_SERVED_MODEL,
    )
    quantization = resolve("VLLM_QUANTIZATION", options.quantization, "")
    port = int(resolve("VLLM_PORT", options.port, "8000"))
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")

    configuration_path = Path(options.config).resolve()
    prompts_path = Path(options.prompts).resolve()
    if not prompts_path.is_file():
        raise FileNotFoundError(f"prompts file does not exist: {prompts_path}")
    _configuration, scenario = load_scenario(configuration_path, options.scenario)
    environment.update(scenario_environment(scenario))
    environment.update(
        {
            "VLLM_DTYPE": resolve("VLLM_DTYPE", None, "auto"),
            "VLLM_ENABLE_CHUNKED_PREFILL": resolve(
                "VLLM_ENABLE_CHUNKED_PREFILL",
                None,
                "true",
            ),
            "VLLM_KV_CACHE_DTYPE": resolve("VLLM_KV_CACHE_DTYPE", None, "auto"),
            "VLLM_MAX_NUM_SEQS": resolve("VLLM_MAX_NUM_SEQS", None, "32"),
            "VLLM_MODEL": model,
            "VLLM_MODEL_REVISION": model_revision,
            "VLLM_PORT": str(port),
            "VLLM_QUANTIZATION": quantization,
            "VLLM_SERVED_MODEL_NAME": served_model_name,
        }
    )
    compose_path = Path(options.compose_file).resolve()
    compose_document = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    image_reference = str(compose_document["services"]["vllm"]["image"])
    compose = [docker, "compose"]
    if env_file.is_file():
        compose.extend(("--env-file", str(env_file.resolve())))
    compose.extend(("--file", str(compose_path)))

    _run_checked([*compose, "config", "--quiet"], environment=environment)
    _run_checked(
        [*compose, "up", "--detach", "--force-recreate", "vllm"],
        environment=environment,
    )
    health_url = f"http://127.0.0.1:{port}/health"
    try:
        _wait_until_healthy(health_url, options.startup_timeout)
    except TimeoutError:
        subprocess.run(
            [*compose, "logs", "--tail", "200", "vllm"],
            check=False,
            env=environment,
            shell=False,
        )
        raise

    runtime = inspect_runtime(
        docker=docker,
        compose=compose,
        environment=environment,
        image_reference=image_reference,
    )
    start_result = {
        "health_url": health_url,
        "model": model,
        "runtime": runtime,
        "scenario": options.scenario,
        "served_model_name": served_model_name,
    }
    print(json.dumps(start_result, indent=2, sort_keys=True))
    if options.start_only:
        return 0

    benchmark_output = Path(options.output or f"benchmark-results/vllm-{options.scenario}.json")
    telemetry_output = Path(
        options.telemetry_output or f"benchmark-results/vllm-{options.scenario}-gpu-telemetry.json"
    )
    manifest_output = Path(
        options.manifest_output or f"benchmark-results/vllm-{options.scenario}-manifest.json"
    )
    benchmark_command = [
        sys.executable,
        str(ROOT / "benchmarks" / "inference" / "vllm_benchmark.py"),
        "--base-url",
        f"http://127.0.0.1:{port}/v1",
        "--model",
        served_model_name,
        "--config",
        str(configuration_path),
        "--prompts",
        str(prompts_path),
        "--scenario",
        options.scenario,
        "--max-error-rate",
        str(options.max_error_rate),
        "--output",
        str(benchmark_output),
    ]
    for name, value in (
        ("--requests-per-level", options.requests_per_level),
        ("--runs", options.runs),
        ("--max-tokens", options.max_tokens),
    ):
        if value is not None:
            benchmark_command.extend((name, str(value)))

    telemetry = TelemetrySession(interval_seconds=options.telemetry_interval)
    telemetry.start()
    benchmark_returncode = 1
    telemetry_error: str | None = None
    try:
        benchmark_returncode = subprocess.run(
            benchmark_command,
            check=False,
            shell=False,
        ).returncode
    finally:
        try:
            telemetry.stop_and_write(telemetry_output)
        except Exception as error:
            telemetry_error = f"{type(error).__name__}: {error}"
    manifest = {
        "schema_version": "1",
        "kind": "local-vllm-benchmark-run",
        "created_at": datetime.now(UTC).isoformat(),
        "configuration": {
            "benchmark_driver": _artifact_entry(
                ROOT / "benchmarks" / "inference" / "vllm_benchmark.py"
            ),
            "config": _artifact_entry(configuration_path),
            "compose": _artifact_entry(compose_path),
            "dtype": environment["VLLM_DTYPE"],
            "enable_chunked_prefill": environment["VLLM_ENABLE_CHUNKED_PREFILL"],
            "engine_args": scenario["engine_args"],
            "kv_cache_dtype": environment["VLLM_KV_CACHE_DTYPE"],
            "max_num_seqs": int(environment["VLLM_MAX_NUM_SEQS"]),
            "model": model,
            "model_revision": model_revision or None,
            "orchestrator": _artifact_entry(Path(__file__).resolve()),
            "prompts": _artifact_entry(prompts_path),
            "quantization": quantization or None,
            "scenario": options.scenario,
            "served_model_name": served_model_name,
            "startup_script": _artifact_entry(ROOT / "scripts" / "start-vllm.sh"),
        },
        "runtime": runtime,
        "artifacts": {
            "benchmark": _artifact_entry(benchmark_output),
            "gpu_telemetry": _artifact_entry(telemetry_output),
        },
        "benchmark_returncode": benchmark_returncode,
        "telemetry": {
            "error": telemetry_error,
            "status": "ok" if telemetry_error is None else "failed",
        },
    }
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "benchmark_output": str(benchmark_output),
                "benchmark_returncode": benchmark_returncode,
                "gpu_telemetry_output": str(telemetry_output),
                "manifest_output": str(manifest_output),
                "telemetry_status": "ok" if telemetry_error is None else "failed",
            },
            indent=2,
            sort_keys=True,
        )
    )
    if telemetry_error is not None:
        print(f"GPU telemetry failed: {telemetry_error}", file=sys.stderr)
        return benchmark_returncode if benchmark_returncode != 0 else 3
    return benchmark_returncode


if __name__ == "__main__":
    raise SystemExit(main())
