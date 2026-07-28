"""Static validation for artifacts that need external tools at deployment time."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELM_TEMPLATES = ROOT / "platform" / "helm" / "ml-platform" / "templates"
IGNORED_PARTS = {
    ".demo",
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".terraform",
    ".tools",
    ".venv",
    ".vinext",
    ".wrangler",
    "__pycache__",
    "benchmark-results",
    "dist",
    "node_modules",
}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _is_ignored(path: Path) -> bool:
    return path.name == "pipeline.yaml" or any(
        part in IGNORED_PARTS for part in path.relative_to(ROOT).parts
    )


def _yaml_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix in {".yaml", ".yml"}
        and HELM_TEMPLATES not in path.parents
        and not _is_ignored(path)
    ]


def _json_files() -> list[Path]:
    return [path for path in ROOT.rglob("*.json") if path.is_file() and not _is_ignored(path)]


def validate_yaml() -> list[str]:
    errors: list[str] = []
    for path in _yaml_files():
        try:
            list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except yaml.YAMLError as error:
            errors.append(f"{path.relative_to(ROOT)}: invalid YAML: {error}")
    return errors


def validate_json() -> list[str]:
    errors: list[str] = []
    for path in _json_files():
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(f"{path.relative_to(ROOT)}: invalid JSON: {error}")
    return errors


def validate_kustomizations() -> list[str]:
    errors: list[str] = []
    for path in ROOT.rglob("kustomization.yaml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for field in ("resources", "components"):
            for resource in document.get(field, []):
                if not isinstance(resource, str):
                    continue
                if resource.startswith(("http://", "https://", "github.com/")):
                    continue
                target = (path.parent / resource).resolve()
                if not target.exists():
                    errors.append(
                        f"{path.relative_to(ROOT)}: {field} target does not exist: {resource}"
                    )
        for patch in document.get("patches", []):
            if isinstance(patch, dict) and isinstance(patch.get("path"), str):
                target = (path.parent / patch["path"]).resolve()
                if not target.exists():
                    errors.append(
                        f"{path.relative_to(ROOT)}: patch does not exist: {patch['path']}"
                    )
    return errors


def validate_kubernetes_secrets() -> list[str]:
    """Prevent accidentally committing live Secret payloads."""

    errors: list[str] = []
    for path in _yaml_files():
        documents: list[Any] = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        for index, document in enumerate(documents, start=1):
            if not isinstance(document, dict) or document.get("kind") != "Secret":
                continue
            if document.get("data") or document.get("stringData"):
                errors.append(
                    f"{path.relative_to(ROOT)} document {index}: committed Secret "
                    "payload; use a secret manager or an example placeholder file"
                )
    return errors


def validate_runbook_references() -> list[str]:
    errors: list[str] = []

    def visit(value: Any, source: Path) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key == "runbook_url" and isinstance(nested, str):
                    target = ROOT / nested
                    if not target.is_file():
                        errors.append(
                            f"{source.relative_to(ROOT)}: runbook does not exist: {nested}"
                        )
                else:
                    visit(nested, source)
        elif isinstance(value, list):
            for nested in value:
                visit(nested, source)

    for path in _yaml_files():
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            visit(document, path)
    return errors


def validate_markdown_links() -> list[str]:
    errors: list[str] = []
    for path in ROOT.rglob("*.md"):
        if not path.is_file() or _is_ignored(path):
            continue
        text = path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            raw_target = match.group(1).strip().strip("<>")
            if raw_target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative_target = raw_target.split("#", maxsplit=1)[0]
            if not relative_target:
                continue
            target = (path.parent / relative_target).resolve()
            try:
                target.relative_to(ROOT)
            except ValueError:
                errors.append(f"{path.relative_to(ROOT)}: link escapes repository: {raw_target}")
                continue
            if not target.exists():
                errors.append(f"{path.relative_to(ROOT)}: linked path does not exist: {raw_target}")
    return errors


def validate_benchmark_evidence() -> list[str]:
    """Verify reviewed benchmark evidence against the source tree and optional raw run."""

    cpu_evidence_path = ROOT / "docs" / "benchmarks" / "evidence" / "local-cpu-load-summary.json"
    if not cpu_evidence_path.is_file():
        return ["missing benchmark evidence: docs/benchmarks/evidence/local-cpu-load-summary.json"]

    evidence = json.loads(cpu_evidence_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    def verify(relative_path: str, expected_hash: str, *, required: bool) -> None:
        target = (ROOT / relative_path).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            errors.append(f"benchmark evidence path escapes repository: {relative_path}")
            return
        if not target.is_file():
            if required:
                errors.append(f"benchmark evidence target does not exist: {relative_path}")
            return
        observed_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if observed_hash != expected_hash.lower():
            errors.append(
                f"benchmark evidence hash mismatch for {relative_path}: "
                f"expected {expected_hash.lower()}, observed {observed_hash}"
            )

    source = evidence.get("source", {})
    verify(
        "benchmarks/load/run.py",
        str(source.get("benchmark_sha256", "")),
        required=True,
    )
    for relative_path, expected_hash in source.get("critical_file_sha256", {}).items():
        verify(str(relative_path), str(expected_hash), required=True)

    artifact = evidence.get("artifact", {})
    # Raw samples are intentionally gitignored; validate them when present locally.
    verify(
        str(artifact.get("raw_output_path", "")),
        str(artifact.get("raw_output_sha256", "")),
        required=False,
    )

    gpu_evidence_path = (
        ROOT / "docs" / "benchmarks" / "evidence" / "local-rtx4080-super-vllm-summary.json"
    )
    if not gpu_evidence_path.is_file():
        errors.append(
            "missing benchmark evidence: "
            "docs/benchmarks/evidence/local-rtx4080-super-vllm-summary.json"
        )
        return errors
    gpu_text = gpu_evidence_path.read_text(encoding="utf-8")
    gpu_evidence = json.loads(gpu_text)
    if gpu_evidence.get("kind") != "local-rtx4080-super-vllm-benchmark-summary":
        errors.append("GPU benchmark evidence has an unexpected kind")
    if gpu_evidence.get("workload", {}).get("total_measured_requests") != 900:
        errors.append("GPU benchmark evidence must contain all 900 measured requests")
    if re.search(r"GPU-[0-9a-fA-F-]{8,}", gpu_text):
        errors.append("GPU benchmark evidence must not publish a device UUID")
    if "HF_TOKEN" in gpu_text:
        errors.append("GPU benchmark evidence must not publish token fields")

    scenario_names = {scenario.get("name") for scenario in gpu_evidence.get("scenarios", [])}
    if scenario_names != {"baseline", "prefix-cache", "constrained-batch"}:
        errors.append("GPU benchmark evidence is missing a required scenario")
    for scenario in gpu_evidence.get("scenarios", []):
        if not scenario.get("quality_gate", {}).get("passed"):
            errors.append(f"GPU benchmark quality gate did not pass: {scenario.get('name')}")
        for raw_artifact in scenario.get("raw_artifacts", {}).values():
            verify(
                str(raw_artifact.get("path", "")),
                str(raw_artifact.get("sha256", "")),
                required=False,
            )
    for source_artifact in gpu_evidence.get("source_artifacts", {}).values():
        verify(
            str(source_artifact.get("path", "")),
            str(source_artifact.get("sha256", "")),
            required=True,
        )
    preflight_artifact = gpu_evidence.get("preflight_artifact", {})
    verify(
        str(preflight_artifact.get("path", "")),
        str(preflight_artifact.get("sha256", "")),
        required=True,
    )
    return errors


def validate_required_evidence() -> list[str]:
    required = (
        "README.md",
        "LICENSE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "pyproject.toml",
        "Dockerfile",
        "compose.yaml",
        "compose.gpu.yaml",
        "docs/architecture/architecture.md",
        "docs/architecture/threat-model.md",
        "docs/acceptance-evidence.md",
        "docs/benchmarks/report.md",
        "docs/benchmarks/evidence/local-rtx4080-super-preflight.json",
        "docs/benchmarks/evidence/local-rtx4080-super-vllm-summary.json",
        "docs/demo-script.md",
        "docs/known-limitations.md",
        "docs/local-gpu.md",
        "docs/roadmap.md",
        "docs/postmortems/2026-07-28-canary-latency-regression.md",
        "runbooks/README.md",
        "platform/helm/ml-platform/Chart.yaml",
        "pipelines/training_pipeline/pipeline.py",
        "scripts/gpu_preflight.py",
        "serving/kserve/predictive/base/inferenceservice.yaml",
        "serving/vllm/overlays/rtx4080-super/kustomization.yaml",
        "observability/prometheus/rules/platform-alerts.yaml",
    )
    errors = [
        f"missing required evidence: {path}" for path in required if not (ROOT / path).exists()
    ]
    minimum_collections = (
        ("architecture decision records", ROOT / "docs" / "adr", "0*.md", 8),
        ("operations runbooks", ROOT / "runbooks", "*.md", 6),
        ("technical articles", ROOT / "docs" / "articles", "*.md", 2),
    )
    for label, directory, pattern, minimum in minimum_collections:
        count = len(list(directory.glob(pattern))) if directory.exists() else 0
        if count < minimum:
            errors.append(f"{label}: expected at least {minimum}, found {count}")
    return errors


def main() -> int:
    validators = (
        validate_yaml,
        validate_json,
        validate_kustomizations,
        validate_kubernetes_secrets,
        validate_runbook_references,
        validate_markdown_links,
        validate_benchmark_evidence,
        validate_required_evidence,
    )
    errors = [error for validator in validators for error in validator()]
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"repository validation passed: {len(_yaml_files())} YAML files and "
        f"{len(_json_files())} JSON files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
