from __future__ import annotations

import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path


def load_gpu_preflight_module():
    path = Path("scripts/gpu_preflight.py").resolve()
    spec = importlib.util.spec_from_file_location("gpu_preflight", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["gpu_preflight"] = module
    spec.loader.exec_module(module)
    return module


def make_runner(module, results):
    calls: list[tuple[str, ...]] = []

    def runner(arguments: Sequence[str], timeout: float):
        del timeout
        command = tuple(arguments)
        calls.append(command)
        key = command[1:]
        return results.get(key, module.CommandResult(127, "", ""))

    return runner, calls


def test_parse_nvidia_smi_csv_preserves_rtx_4080_super_fields() -> None:
    module = load_gpu_preflight_module()

    devices = module.parse_nvidia_smi_csv(
        "0, NVIDIA GeForce RTX 4080 SUPER, 610.74, 16376 MiB, 8.9\n"
    )

    assert devices == [
        {
            "compute_capability": 8.9,
            "driver_version": "610.74",
            "index": 0,
            "memory_total_mib": 16376,
            "name": "NVIDIA GeForce RTX 4080 SUPER",
        }
    ]


def test_ready_windows_report_uses_only_read_only_commands() -> None:
    module = load_gpu_preflight_module()
    results = {
        (
            "--query-gpu=index,name,driver_version,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ): module.CommandResult(
            0,
            "0, NVIDIA GeForce RTX 4080 SUPER, 610.74, 16376, 8.9\n",
            "",
        ),
        ("--version",): module.CommandResult(0, "Docker version 28.0.0\n", ""),
        ("compose", "version"): module.CommandResult(0, "Docker Compose version v2.36.0\n", ""),
        ("run", "--help"): module.CommandResult(0, "Options:\n      --gpus gpu-request\n", ""),
        ("info", "--format", "{{json .}}"): module.CommandResult(
            0,
            (
                '{"ServerVersion":"28.0.0","OSType":"linux",'
                '"DefaultRuntime":"runc","Runtimes":{"runc":{},"nvidia":{}}}'
            ),
            "",
        ),
        ("--status",): module.CommandResult(0, "Default Version: 2\n", ""),
        ("--list", "--verbose"): module.CommandResult(0, "  Ubuntu  Running  2\n", ""),
    }
    runner, calls = make_runner(module, results)

    def finder(name: str) -> str | None:
        return {
            "docker": "docker.exe",
            "nvidia-smi": "nvidia-smi.exe",
            "wsl.exe": "wsl.exe",
        }.get(name)

    report = module.collect_report(
        runner=runner,
        finder=finder,
        system_name="Windows",
    )

    assert report["ready"] is True
    assert report["blocked_reasons"] == []
    assert report["checks"]["nvidia"]["devices"][0]["name"].endswith("RTX 4080 SUPER")
    assert report["checks"]["docker"]["nvidia_runtime_detected"] is True
    assert report["checks"]["wsl"]["wsl2_detected"] is True
    assert all(command[1:] != ("pull",) for command in calls)
    assert not any(
        command[1:2] == ("create",) or (command[1:2] == ("run",) and command[2:] != ("--help",))
        for command in calls
    )


def test_missing_prerequisites_produce_stable_blocking_codes() -> None:
    module = load_gpu_preflight_module()
    runner, calls = make_runner(module, {})

    report = module.collect_report(
        runner=runner,
        finder=lambda _name: None,
        system_name="Windows",
    )

    assert report["ready"] is False
    assert [reason["code"] for reason in report["blocked_reasons"]] == [
        "nvidia_smi.not_found",
        "docker.not_found",
        "wsl.not_found",
    ]
    assert calls == []


def test_docker_static_gpu_check_blocks_missing_nvidia_runtime() -> None:
    module = load_gpu_preflight_module()
    results = {
        (
            "--query-gpu=index,name,driver_version,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ): module.CommandResult(0, "0, NVIDIA RTX 6000 Ada, 570.00, 49140, 8.9\n", ""),
        ("--version",): module.CommandResult(0, "Docker version 28.0.0\n", ""),
        ("compose", "version"): module.CommandResult(0, "Docker Compose version v2.36.0\n", ""),
        ("run", "--help"): module.CommandResult(0, "      --gpus gpu-request\n", ""),
        ("info", "--format", "{{json .}}"): module.CommandResult(
            0,
            '{"ServerVersion":"28.0.0","OSType":"linux","Runtimes":{"runc":{}}}',
            "",
        ),
    }
    runner, _calls = make_runner(module, results)
    report = module.collect_report(
        runner=runner,
        finder=lambda name: f"/usr/bin/{name}" if name in {"docker", "nvidia-smi"} else None,
        system_name="Linux",
    )

    assert report["ready"] is False
    assert [reason["code"] for reason in report["blocked_reasons"]] == [
        "docker.nvidia_runtime_not_detected"
    ]
    assert report["checks"]["wsl"] == {
        "applicable": False,
        "available": None,
        "status": "not_applicable",
        "version": None,
        "wsl2_detected": None,
    }


def test_windows_docker_desktop_gpu_route_does_not_require_named_runtime() -> None:
    module = load_gpu_preflight_module()
    results = {
        (
            "--query-gpu=index,name,driver_version,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ): module.CommandResult(
            0,
            "0, NVIDIA GeForce RTX 4080 SUPER, 610.74, 16376, 8.9\n",
            "",
        ),
        ("--version",): module.CommandResult(0, "Docker version 28.0.0\n", ""),
        ("compose", "version"): module.CommandResult(0, "Docker Compose version v2.36.0\n", ""),
        ("run", "--help"): module.CommandResult(0, "      --gpus gpu-request\n", ""),
        ("info", "--format", "{{json .}}"): module.CommandResult(
            0,
            (
                '{"ServerVersion":"28.0.0","OSType":"linux",'
                '"OperatingSystem":"Docker Desktop","Name":"docker-desktop",'
                '"Runtimes":{"io.containerd.runc.v2":{},"runc":{}}}'
            ),
            "",
        ),
        ("--status",): module.CommandResult(0, "Default Version: 2\n", ""),
        ("--list", "--verbose"): module.CommandResult(0, "  docker-desktop  Running  2\n", ""),
    }
    runner, _calls = make_runner(module, results)
    report = module.collect_report(
        runner=runner,
        finder=lambda name: {
            "docker": "docker.exe",
            "nvidia-smi": "nvidia-smi.exe",
            "wsl.exe": "wsl.exe",
        }.get(name),
        system_name="Windows",
    )

    assert report["ready"] is True
    docker = report["checks"]["docker"]
    assert docker["nvidia_runtime_detected"] is False
    assert docker["docker_desktop_detected"] is True
    assert docker["gpu_runtime_route"] == "docker-desktop-wsl2"


def test_vram_threshold_is_enforced() -> None:
    module = load_gpu_preflight_module()
    result = module.CommandResult(0, "0, NVIDIA T4, 570.00, 8192, 7.5\n", "")

    report, issues = module._probe_nvidia(
        lambda _arguments, _timeout: result,
        lambda _name: "nvidia-smi",
        minimum_vram_mib=12_000,
    )

    assert report["compatible_device_count"] == 0
    assert [issue["code"] for issue in issues] == ["gpu.no_compatible_device"]


def test_traditional_chinese_wsl_status_is_detected() -> None:
    module = load_gpu_preflight_module()

    assert module._wsl2_from_status("\u9810\u8a2d\u7248\u672c\uff1a 2\n") is True


def test_find_executable_supports_per_user_docker_desktop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_gpu_preflight_module()
    docker = tmp_path / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
    docker.parent.mkdir(parents=True)
    docker.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)

    assert module.find_executable("docker") == str(docker)
