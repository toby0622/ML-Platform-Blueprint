"""Read-only preflight checks for the local NVIDIA vLLM runtime.

The probe deliberately does not pull images or start containers. It verifies the
host GPU, Docker/Compose, the Docker daemon's static GPU declarations, and WSL 2
when running on Windows.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MINIMUM_COMPUTE_CAPABILITY = 7.5
DEFAULT_MINIMUM_VRAM_MIB = 12_000
COMMAND_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class CommandResult:
    """Normalized result from one command invocation."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], float], CommandResult]
ExecutableFinder = Callable[[str], str | None]


def find_executable(name: str) -> str | None:
    """Find a CLI, including current per-user Docker Desktop installations."""

    discovered = shutil.which(name)
    if discovered is not None or name.lower() not in {"docker", "docker.exe"}:
        return discovered

    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("PROGRAMFILES")
    if local_app_data:
        candidates.append(
            Path(local_app_data) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
        )
    if program_files:
        candidates.append(
            Path(program_files) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
        )
    return next((str(candidate) for candidate in candidates if candidate.is_file()), None)


def _decode_output(value: bytes) -> str:
    """Decode command output, including the UTF-16 output used by some WSL builds."""

    if not value:
        return ""
    if value.startswith((b"\xff\xfe", b"\xfe\xff")) or value.count(b"\x00") > len(value) // 4:
        return value.decode("utf-16", errors="replace").replace("\ufeff", "")
    return value.decode("utf-8", errors="replace")


def run_command(arguments: Sequence[str], timeout: float) -> CommandResult:
    """Run an argv-only, read-only command without involving a shell."""

    try:
        completed = subprocess.run(
            list(arguments),
            check=False,
            capture_output=True,
            shell=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return CommandResult(returncode=127, stdout="", stderr="")
    return CommandResult(
        returncode=completed.returncode,
        stdout=_decode_output(completed.stdout),
        stderr=_decode_output(completed.stderr),
    )


def _first_line(value: str) -> str | None:
    line = next((line.strip() for line in value.splitlines() if line.strip()), "")
    return line or None


def _parse_int(value: str) -> int | None:
    match = re.match(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))", value)
    if match is None:
        return None
    try:
        return round(float(match.group(1)))
    except ValueError:
        return None


def _parse_float(value: str) -> float | None:
    try:
        return float(value.strip())
    except ValueError:
        return None


def parse_nvidia_smi_csv(output: str) -> list[dict[str, Any]]:
    """Parse the stable CSV output requested from ``nvidia-smi``."""

    devices: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO(output))
    for row in reader:
        if not row or all(not value.strip() for value in row):
            continue
        if len(row) != 5:
            raise ValueError("unexpected nvidia-smi column count")
        index = _parse_int(row[0])
        memory_mib = _parse_int(row[3])
        compute_capability = _parse_float(row[4])
        if index is None:
            raise ValueError("invalid nvidia-smi GPU index")
        devices.append(
            {
                "compute_capability": compute_capability,
                "driver_version": row[2].strip() or None,
                "index": index,
                "memory_total_mib": memory_mib,
                "name": row[1].strip() or None,
            }
        )
    return sorted(devices, key=lambda device: int(device["index"]))


def _probe_nvidia(
    runner: CommandRunner,
    finder: ExecutableFinder,
    minimum_vram_mib: int,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    executable = finder("nvidia-smi")
    report: dict[str, Any] = {
        "available": executable is not None,
        "compatible_device_count": 0,
        "devices": [],
        "minimum_compute_capability": MINIMUM_COMPUTE_CAPABILITY,
        "minimum_vram_mib": minimum_vram_mib,
        "query_succeeded": False,
    }
    if executable is None:
        return report, [
            {
                "code": "nvidia_smi.not_found",
                "message": "nvidia-smi was not found; install or expose the NVIDIA display driver.",
            }
        ]

    result = runner(
        (
            executable,
            "--query-gpu=index,name,driver_version,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ),
        COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return report, [
            {
                "code": "nvidia_smi.query_failed",
                "message": "nvidia-smi could not query GPU inventory.",
            }
        ]

    try:
        devices = parse_nvidia_smi_csv(result.stdout)
    except ValueError:
        return report, [
            {
                "code": "nvidia_smi.invalid_output",
                "message": "nvidia-smi returned an unexpected GPU inventory format.",
            }
        ]

    report["devices"] = devices
    report["query_succeeded"] = True
    compatible_devices = [
        device
        for device in devices
        if device["compute_capability"] is not None
        and device["compute_capability"] >= MINIMUM_COMPUTE_CAPABILITY
        and device["memory_total_mib"] is not None
        and device["memory_total_mib"] >= minimum_vram_mib
    ]
    report["compatible_device_count"] = len(compatible_devices)
    if compatible_devices:
        return report, []
    return report, [
        {
            "code": "gpu.no_compatible_device",
            "message": (
                "No GPU meets the required compute capability "
                f"{MINIMUM_COMPUTE_CAPABILITY:.1f} and {minimum_vram_mib} MiB VRAM."
            ),
        }
    ]


def _parse_docker_info(output: str) -> dict[str, Any] | None:
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _probe_docker(
    runner: CommandRunner,
    finder: ExecutableFinder,
    system_name: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    executable = finder("docker")
    report: dict[str, Any] = {
        "available": executable is not None,
        "client_version": None,
        "compose_available": False,
        "compose_version": None,
        "daemon_reachable": False,
        "default_runtime": None,
        "docker_desktop_detected": False,
        "gpu_capability_check": "static_only_no_container_started",
        "gpu_runtime_route": None,
        "linux_engine": False,
        "nvidia_runtime_detected": False,
        "operating_system": None,
        "os_type": None,
        "runtimes": [],
        "server_version": None,
        "supports_gpus_flag": False,
    }
    if executable is None:
        return report, [
            {
                "code": "docker.not_found",
                "message": (
                    "Docker CLI was not found; install Docker with a Linux container engine."
                ),
            }
        ]

    issues: list[dict[str, str]] = []
    version = runner((executable, "--version"), COMMAND_TIMEOUT_SECONDS)
    if version.returncode == 0:
        report["client_version"] = _first_line(version.stdout)

    compose = runner((executable, "compose", "version"), COMMAND_TIMEOUT_SECONDS)
    report["compose_available"] = compose.returncode == 0
    if compose.returncode == 0:
        report["compose_version"] = _first_line(compose.stdout)
    else:
        issues.append(
            {
                "code": "docker.compose_not_found",
                "message": "Docker Compose v2 is not available through `docker compose`.",
            }
        )

    run_help = runner((executable, "run", "--help"), COMMAND_TIMEOUT_SECONDS)
    report["supports_gpus_flag"] = run_help.returncode == 0 and bool(
        re.search(r"(?m)^\s*--gpus(?:\s|$)", run_help.stdout)
    )
    if not report["supports_gpus_flag"]:
        issues.append(
            {
                "code": "docker.gpus_flag_not_found",
                "message": "Docker CLI does not advertise the `docker run --gpus` option.",
            }
        )

    info = runner(
        (executable, "info", "--format", "{{json .}}"),
        COMMAND_TIMEOUT_SECONDS,
    )
    if info.returncode != 0:
        issues.append(
            {
                "code": "docker.daemon_unreachable",
                "message": "Docker daemon is not reachable.",
            }
        )
        return report, issues

    parsed = _parse_docker_info(info.stdout)
    if parsed is None:
        issues.append(
            {
                "code": "docker.info_invalid",
                "message": "Docker daemon returned an unexpected info document.",
            }
        )
        return report, issues

    report["daemon_reachable"] = True
    report["server_version"] = parsed.get("ServerVersion")
    report["os_type"] = parsed.get("OSType")
    report["linux_engine"] = str(parsed.get("OSType", "")).lower() == "linux"
    report["default_runtime"] = parsed.get("DefaultRuntime")
    report["operating_system"] = parsed.get("OperatingSystem")
    daemon_name = str(parsed.get("Name", ""))
    operating_system = str(parsed.get("OperatingSystem", ""))
    report["docker_desktop_detected"] = (
        "docker desktop" in operating_system.lower() or daemon_name.lower() == "docker-desktop"
    )
    raw_runtimes = parsed.get("Runtimes")
    runtimes = sorted(str(name) for name in raw_runtimes) if isinstance(raw_runtimes, dict) else []
    report["runtimes"] = runtimes
    report["nvidia_runtime_detected"] = any("nvidia" in runtime.lower() for runtime in runtimes)
    docker_desktop_gpu_route = (
        system_name.lower() == "windows"
        and report["docker_desktop_detected"]
        and report["supports_gpus_flag"]
    )
    if report["nvidia_runtime_detected"]:
        report["gpu_runtime_route"] = "nvidia-runtime"
    elif docker_desktop_gpu_route:
        report["gpu_runtime_route"] = "docker-desktop-wsl2"

    if not report["linux_engine"]:
        issues.append(
            {
                "code": "docker.linux_engine_required",
                "message": "vLLM requires Docker to use a Linux container engine.",
            }
        )
    if report["gpu_runtime_route"] is None:
        issues.append(
            {
                "code": "docker.nvidia_runtime_not_detected",
                "message": (
                    "Docker info does not declare an NVIDIA runtime; configure NVIDIA "
                    "Container Toolkit or Docker Desktop GPU support."
                ),
            }
        )
    return report, issues


def _wsl2_from_status(output: str) -> bool:
    normalized = output.replace("\x00", "")
    return bool(
        re.search(
            r"(?im)(?:default\s+version|預設版本|默认版本)\s*[:\uFF1A]\s*2(?:\s|$)",
            normalized,
        )
    )


def _wsl2_from_list(output: str) -> bool:
    normalized = output.replace("\x00", "")
    return any(re.search(r"\s2\s*$", line) for line in normalized.splitlines())


def _probe_wsl(
    runner: CommandRunner,
    finder: ExecutableFinder,
    system_name: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    applicable = system_name.lower() == "windows"
    report: dict[str, Any] = {
        "applicable": applicable,
        "available": None,
        "status": "not_applicable",
        "version": None,
        "wsl2_detected": None,
    }
    if not applicable:
        return report, []

    executable = finder("wsl.exe") or finder("wsl")
    report["available"] = executable is not None
    if executable is None:
        report["status"] = "not_found"
        report["wsl2_detected"] = False
        return report, [
            {
                "code": "wsl.not_found",
                "message": "WSL was not found; vLLM has no native Windows runtime.",
            }
        ]

    version = runner((executable, "--version"), COMMAND_TIMEOUT_SECONDS)
    if version.returncode == 0:
        report["version"] = _first_line(version.stdout)
    status = runner((executable, "--status"), COMMAND_TIMEOUT_SECONDS)
    distributions = runner((executable, "--list", "--verbose"), COMMAND_TIMEOUT_SECONDS)
    query_succeeded = status.returncode == 0 or distributions.returncode == 0
    wsl2_detected = (status.returncode == 0 and _wsl2_from_status(status.stdout)) or (
        distributions.returncode == 0 and _wsl2_from_list(distributions.stdout)
    )
    report["wsl2_detected"] = wsl2_detected
    if wsl2_detected:
        report["status"] = "ready"
        return report, []

    report["status"] = "installed_without_wsl2" if query_succeeded else "query_failed"
    return report, [
        {
            "code": "wsl.wsl2_not_detected",
            "message": "WSL 2 could not be verified; Windows vLLM support requires WSL 2.",
        }
    ]


def collect_report(
    *,
    minimum_vram_mib: int = DEFAULT_MINIMUM_VRAM_MIB,
    runner: CommandRunner = run_command,
    finder: ExecutableFinder = find_executable,
    system_name: str | None = None,
) -> dict[str, Any]:
    """Collect all preflight checks into a deterministic JSON-compatible report."""

    resolved_system = system_name or platform.system()
    nvidia, nvidia_issues = _probe_nvidia(runner, finder, minimum_vram_mib)
    docker, docker_issues = _probe_docker(runner, finder, resolved_system)
    wsl, wsl_issues = _probe_wsl(runner, finder, resolved_system)
    blocked_reasons = [*nvidia_issues, *docker_issues, *wsl_issues]
    return {
        "blocked_reasons": blocked_reasons,
        "checks": {
            "docker": docker,
            "nvidia": nvidia,
            "wsl": wsl,
        },
        "host_os": resolved_system,
        "ready": not blocked_reasons,
        "schema_version": 1,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify local NVIDIA vLLM prerequisites without starting containers."
    )
    parser.add_argument(
        "--minimum-vram-mib",
        type=int,
        default=DEFAULT_MINIMUM_VRAM_MIB,
        help=f"minimum usable GPU memory in MiB (default: {DEFAULT_MINIMUM_VRAM_MIB})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="also write the JSON report to this path",
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    options = parser.parse_args(arguments)
    if options.minimum_vram_mib <= 0:
        parser.error("--minimum-vram-mib must be greater than zero")
    report = collect_report(minimum_vram_mib=options.minimum_vram_mib)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if options.output is not None:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
