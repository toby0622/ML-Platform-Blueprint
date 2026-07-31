from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import yaml


def test_repository_artifacts_are_valid() -> None:
    path = Path("scripts/validate_repository.py").resolve()
    spec = importlib.util.spec_from_file_location("validate_repository", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_repository"] = module
    spec.loader.exec_module(module)

    assert module.main() == 0


def test_source_hash_validation_accepts_only_newline_encoding_changes(
    tmp_path: Path,
) -> None:
    path = Path("scripts/validate_repository.py").resolve()
    spec = importlib.util.spec_from_file_location("validate_repository", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_repository"] = module
    spec.loader.exec_module(module)

    source = tmp_path / "source.py"
    lf_payload = b"first = 1\nsecond = 2\n"
    source.write_bytes(lf_payload)
    crlf_hash = hashlib.sha256(lf_payload.replace(b"\n", b"\r\n")).hexdigest()

    assert crlf_hash in module._sha256_candidates(
        source,
        allow_text_newline_variants=True,
    )
    assert crlf_hash not in module._sha256_candidates(
        source,
        allow_text_newline_variants=False,
    )
    assert hashlib.sha256(b"first = 1\nsecond = 3\n").hexdigest() not in (
        module._sha256_candidates(
            source,
            allow_text_newline_variants=True,
        )
    )
    assert hashlib.sha256(lf_payload.replace(b"\n", b"\r")).hexdigest() not in (
        module._sha256_candidates(
            source,
            allow_text_newline_variants=True,
        )
    )


def test_kserve_custom_runtime_uses_the_v017_storage_contract() -> None:
    service = yaml.safe_load(
        Path("serving/kserve/predictive/base/inferenceservice.yaml").read_text(encoding="utf-8")
    )
    predictor = service["spec"]["predictor"]
    storage = predictor["storageUris"][0]
    container = predictor["containers"][0]

    assert storage["mountPath"] == "/mnt/models"
    assert storage["uri"].startswith("s3://REPLACE_WITH_ARTIFACT_BUCKET/tenants/team-a/")
    assert "/mnt/models/model.json" in container["args"]
    assert "STORAGE_URI" not in {variable["name"] for variable in container.get("env", [])}

    patch = yaml.safe_load(
        Path("serving/kserve/predictive/overlays/canary/canary-patch.yaml").read_text(
            encoding="utf-8"
        )
    )
    storage_patch = next(
        operation for operation in patch if operation["path"] == "/spec/predictor/storageUris/0/uri"
    )
    assert storage_patch["value"].startswith("s3://REPLACE_WITH_ARTIFACT_BUCKET/tenants/team-a/")


def test_production_mlflow_image_is_built_and_released() -> None:
    values = yaml.safe_load(
        Path("platform/mlflow/values-production.yaml").read_text(encoding="utf-8")
    )
    workflow = yaml.safe_load(Path(".github/workflows/release.yml").read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["publish"]["strategy"]["matrix"]["include"]
    mlflow_build = next(
        entry for entry in matrix if entry["name"] == "ml-platform-blueprint-mlflow"
    )

    assert values["image"]["repository"] == "ghcr.io/toby0622/ml-platform-blueprint-mlflow"
    assert mlflow_build["dockerfile"] == "infra/images/mlflow/Dockerfile"
    dockerfile = Path(mlflow_build["dockerfile"]).read_text(encoding="utf-8")
    assert "boto3" in dockerfile
    assert "psycopg2-binary" in dockerfile


def test_python_runtime_images_enforce_known_security_floors() -> None:
    expected_pip_uninstalls = {
        Path("Dockerfile"): 2,
        Path("Dockerfile.pipeline"): 1,
        Path("infra/images/mlflow/Dockerfile"): 1,
    }
    for path, uninstall_count in expected_pip_uninstalls.items():
        dockerfile = path.read_text(encoding="utf-8")
        assert '"msgpack>=1.2.1"' in dockerfile
        assert '"setuptools>=78.1.1"' in dockerfile
        assert "python -m pip check" in dockerfile
        assert dockerfile.count("python -m pip uninstall --yes pip") == uninstall_count
        assert dockerfile.count("find_spec('pip') is None") == uninstall_count
        assert dockerfile.index("python -m pip check") < dockerfile.index(
            "python -m pip uninstall --yes pip"
        )

    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert workflow.count("find_spec('pip') is None") == 4


def test_dependabot_separates_routine_updates_from_platform_migrations() -> None:
    config = yaml.safe_load(Path(".github/dependabot.yml").read_text(encoding="utf-8"))
    updates = {entry["package-ecosystem"]: entry for entry in config["updates"]}

    pip_groups = updates["pip"]["groups"]
    assert pip_groups == {
        "runtime": {
            "patterns": ["fastapi", "numpy", "pydantic", "uvicorn"],
            "update-types": ["patch", "minor"],
        },
        "development-tools": {
            "patterns": [
                "hatchling",
                "httpx",
                "mypy",
                "pytest",
                "pytest-cov",
                "pyyaml",
                "ruff",
            ],
            "update-types": ["patch", "minor"],
        },
        "observability": {
            "patterns": ["opentelemetry-*"],
            "update-types": ["patch", "minor"],
        },
    }
    grouped_python_dependencies = {
        dependency for group in pip_groups.values() for dependency in group["patterns"]
    }
    assert "*" not in grouped_python_dependencies
    assert {"kfp", "mlflow"}.isdisjoint(grouped_python_dependencies)
    pip_ignore = {rule["dependency-name"]: rule for rule in updates["pip"]["ignore"]}
    assert pip_ignore == {
        "kfp": {
            "dependency-name": "kfp",
            "versions": [">2.16.0"],
            "update-types": [
                "version-update:semver-major",
                "version-update:semver-minor",
                "version-update:semver-patch",
            ],
        },
        "mypy": {
            "dependency-name": "mypy",
            "versions": [">=2"],
            "update-types": ["version-update:semver-major"],
        },
    }

    python_ignore = next(
        rule for rule in updates["docker"]["ignore"] if rule["dependency-name"] == "python"
    )
    assert set(python_ignore["update-types"]) == {
        "version-update:semver-major",
        "version-update:semver-minor",
    }
    assert updates["github-actions"]["groups"] == {
        "github-actions": {
            "patterns": ["*"],
            "exclude-patterns": ["actions/attest-build-provenance"],
        }
    }


def test_portal_is_built_released_and_wired_through_the_server_side_bff() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    portal = compose["services"]["portal"]
    assert portal["ports"] == ["127.0.0.1:${PORTAL_PORT:-3001}:3000"]
    assert portal["environment"]["PLATFORM_API_URL"] == "http://platform-api:8080"
    assert "NEXT_PUBLIC" not in json.dumps(portal)
    assert {"control", "portal-egress"} == set(portal["networks"])

    workflow = yaml.safe_load(Path(".github/workflows/release.yml").read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["publish"]["strategy"]["matrix"]["include"]
    portal_build = next(
        entry for entry in matrix if entry["name"] == "ml-platform-blueprint-portal"
    )
    assert portal_build == {
        "name": "ml-platform-blueprint-portal",
        "context": "./portal",
        "dockerfile": "portal/Dockerfile",
    }

    values = yaml.safe_load(
        Path("platform/helm/ml-platform/values.yaml").read_text(encoding="utf-8")
    )
    assert values["portal"]["enabled"] is True
    assert values["portal"]["image"]["repository"].endswith("ml-platform-blueprint-portal")
    assert Path("portal/app/api/platform/[...path]/route.ts").is_file()
    assert Path("portal/app/api/llm/chat/route.ts").is_file()
    assert Path("portal/public/og.png").stat().st_size > 100_000


def test_pod_identity_and_artifact_egress_are_explicit() -> None:
    policies = list(
        yaml.safe_load_all(
            Path("platform/tenants/network-policies.yaml").read_text(encoding="utf-8")
        )
    )
    tenant_policies = [
        policy for policy in policies if policy["metadata"]["name"] == "allow-tenant-and-platform"
    ]
    assert {policy["metadata"]["namespace"] for policy in tenant_policies} == {
        "team-a",
        "team-b",
    }
    for policy in tenant_policies:
        egress = policy["spec"]["egress"]
        assert any(
            destination.get("ipBlock", {}).get("cidr") == "169.254.170.23/32"
            and {"protocol": "TCP", "port": 80} in rule.get("ports", [])
            for rule in egress
            for destination in rule.get("to", [])
        )
        assert any(
            destination.get("ipBlock", {}).get("cidr") == "0.0.0.0/0"
            and {"protocol": "TCP", "port": 443} in rule.get("ports", [])
            for rule in egress
            for destination in rule.get("to", [])
        )

    mlflow_values = yaml.safe_load(
        Path("platform/mlflow/values-production.yaml").read_text(encoding="utf-8")
    )
    assert mlflow_values["networkPolicy"]["additionalEgressRules"] == [
        {
            "to": [{"ipBlock": {"cidr": "169.254.170.23/32"}}],
            "ports": [{"protocol": "TCP", "port": 80}],
        }
    ]


def test_local_vllm_profile_reserves_one_gpu_with_safe_defaults() -> None:
    compose = yaml.safe_load(Path("compose.gpu.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["vllm"]
    reservation = service["deploy"]["resources"]["reservations"]["devices"][0]

    assert service["image"] == (
        "vllm/vllm-openai:v0.23.0"
        "@sha256:6d8429e38e3747723ca07ee1b17972e09bb9c51c4032b266f24fb1cc3b22ed8f"
    )
    assert service["ipc"] == "host"
    assert service["ports"] == ["127.0.0.1:${VLLM_PORT:-8000}:8000"]
    assert reservation == {
        "driver": "nvidia",
        "count": 1,
        "capabilities": ["gpu"],
    }
    assert service["environment"]["VLLM_GPU_MEMORY_UTILIZATION"].endswith(":-0.75}")
    assert service["environment"]["VLLM_MODEL"].endswith(":-Qwen/Qwen2.5-1.5B-Instruct}")


def test_reviewed_gpu_evidence_is_complete_and_secret_free() -> None:
    path = Path("docs/benchmarks/evidence/local-rtx4080-super-vllm-summary.json")
    text = path.read_text(encoding="utf-8")
    evidence = json.loads(text)

    assert evidence["workload"]["total_measured_requests"] == 900
    assert {scenario["name"] for scenario in evidence["scenarios"]} == {
        "baseline",
        "prefix-cache",
        "constrained-batch",
    }
    assert all(scenario["quality_gate"]["passed"] for scenario in evidence["scenarios"])
    assert "GPU-5c21c5f1" not in text
    assert "HF_TOKEN" not in text


def test_rtx_4080_super_kserve_overlay_is_single_replica_and_exclusive() -> None:
    patch = yaml.safe_load(
        Path("serving/vllm/overlays/rtx4080-super/rtx4080-super-patch.yaml").read_text(
            encoding="utf-8"
        )
    )
    predictor = patch["spec"]["predictor"]
    model = predictor["model"]

    assert predictor["minReplicas"] == predictor["maxReplicas"] == 1
    assert predictor["nodeSelector"]["ml-platform.io/accelerator"] == "nvidia-ada-16gb"
    assert model["runtimeVersion"] == "v0.17.0"
    assert model["resources"]["requests"]["nvidia.com/gpu"] == "1"
    assert model["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert model["storageUri"] == (
        "hf://Qwen/Qwen2.5-1.5B-Instruct:989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
    )
