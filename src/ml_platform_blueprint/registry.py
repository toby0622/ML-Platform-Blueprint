"""SQLite metadata registry and content-addressed local artifact store."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .domain import ConflictError, DeploymentState, ModelVersion, NotFoundError
from .model import ModelArtifact
from .utils import (
    atomic_write_text,
    canonical_json,
    sha256_bytes,
    utc_now,
    validate_resource_name,
)


class Registry:
    """Durable reference registry with lineage, aliases, deployments, and audit."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir.resolve()
        self.database_path = self.state_dir / "registry.sqlite3"
        self.artifact_root = self.state_dir / "artifacts"
        self._initialization_lock = threading.Lock()
        self._initialized = False
        self.initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._initialization_lock:
            if self._initialized:
                return
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self.artifact_root.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(
                    """
                    PRAGMA journal_mode = WAL;

                    CREATE TABLE IF NOT EXISTS runs (
                        run_id TEXT PRIMARY KEY,
                        tenant TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        code_revision TEXT NOT NULL,
                        dataset_sha256 TEXT NOT NULL,
                        parameters_json TEXT NOT NULL,
                        metrics_json TEXT,
                        error TEXT,
                        started_at TEXT NOT NULL,
                        ended_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS models (
                        tenant TEXT NOT NULL,
                        name TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (tenant, name)
                    );

                    CREATE TABLE IF NOT EXISTS model_versions (
                        tenant TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        run_id TEXT NOT NULL UNIQUE,
                        stage TEXT NOT NULL,
                        artifact_path TEXT NOT NULL,
                        artifact_sha256 TEXT NOT NULL,
                        dataset_sha256 TEXT NOT NULL,
                        code_revision TEXT NOT NULL,
                        parameters_json TEXT NOT NULL,
                        metrics_json TEXT NOT NULL,
                        model_card_path TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (tenant, model_name, version),
                        FOREIGN KEY (run_id) REFERENCES runs(run_id)
                    );

                    CREATE TABLE IF NOT EXISTS aliases (
                        tenant TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        alias TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (tenant, model_name, alias)
                    );

                    CREATE TABLE IF NOT EXISTS deployments (
                        tenant TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        stable_version INTEGER NOT NULL,
                        canary_version INTEGER,
                        canary_weight INTEGER NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (tenant, model_name)
                    );

                    CREATE TABLE IF NOT EXISTS deployment_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        action TEXT NOT NULL,
                        stable_version INTEGER NOT NULL,
                        canary_version INTEGER,
                        canary_weight INTEGER NOT NULL,
                        actor TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS audit_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        tenant TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        version INTEGER,
                        actor TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_versions_model
                    ON model_versions(tenant, model_name, version DESC);

                    CREATE INDEX IF NOT EXISTS idx_audit_model
                    ON audit_events(tenant, model_name, id DESC);
                    """
                )
            self._initialized = True

    def check_ready(self) -> bool:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT 1").fetchone()
                return row is not None and int(row[0]) == 1
        except sqlite3.Error:
            return False

    @staticmethod
    def _validate_identity(tenant: str, model_name: str) -> None:
        validate_resource_name(tenant, "tenant")
        validate_resource_name(model_name, "model_name")

    def create_run(
        self,
        *,
        run_id: str,
        tenant: str,
        model_name: str,
        code_revision: str,
        dataset_sha256: str,
        parameters: dict[str, Any],
    ) -> None:
        self._validate_identity(tenant, model_name)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, tenant, model_name, status, code_revision,
                    dataset_sha256, parameters_json, started_at
                ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?)
                """,
                (
                    run_id,
                    tenant,
                    model_name,
                    code_revision,
                    dataset_sha256,
                    canonical_json(parameters),
                    utc_now(),
                ),
            )

    def complete_run(self, run_id: str, metrics: dict[str, float]) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = 'succeeded', metrics_json = ?, ended_at = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (canonical_json(metrics), utc_now(), run_id),
            )
            if cursor.rowcount != 1:
                raise ConflictError(f"run {run_id!r} is not in running state")

    def fail_run(self, run_id: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = 'failed', error = ?, ended_at = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (error[:2000], utc_now(), run_id),
            )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "tenant": row["tenant"],
            "model_name": row["model_name"],
            "status": row["status"],
            "code_revision": row["code_revision"],
            "dataset_sha256": row["dataset_sha256"],
            "parameters": json.loads(row["parameters_json"]),
            "metrics": json.loads(row["metrics_json"]) if row["metrics_json"] else None,
            "error": row["error"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"run {run_id!r} does not exist")
        return self._row_to_run(row)

    def list_runs(
        self,
        tenant: str,
        *,
        model_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        validate_resource_name(tenant, "tenant")
        bounded_limit = max(1, min(limit, 500))
        query = "SELECT * FROM runs WHERE tenant = ?"
        parameters: list[str | int] = [tenant]
        if model_name is not None:
            validate_resource_name(model_name, "model_name")
            query += " AND model_name = ?"
            parameters.append(model_name)
        query += " ORDER BY started_at DESC LIMIT ?"
        parameters.append(bounded_limit)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_run(row) for row in rows]

    @staticmethod
    def _model_card(
        *,
        tenant: str,
        model_name: str,
        version: int,
        run_id: str,
        code_revision: str,
        dataset_sha256: str,
        artifact_sha256: str,
        parameters: dict[str, Any],
        metrics: dict[str, float],
    ) -> str:
        metric_rows = "\n".join(
            f"| `{key}` | {value:.6f} |" for key, value in sorted(metrics.items())
        )
        parameter_rows = "\n".join(
            f"| `{key}` | `{value}` |" for key, value in sorted(parameters.items())
        )
        return f"""# Model Card: {tenant}/{model_name} v{version}

## Intended use

Reference binary churn-risk classifier for validating the ML platform lifecycle.
It is trained on deterministic synthetic data and must not be used for real
customer decisions.

## Lineage

| Field | Value |
|---|---|
| Tenant | `{tenant}` |
| Model | `{model_name}` |
| Version | `{version}` |
| Pipeline run | `{run_id}` |
| Code revision | `{code_revision}` |
| Dataset SHA-256 | `{dataset_sha256}` |
| Artifact SHA-256 | `{artifact_sha256}` |

## Parameters

| Parameter | Value |
|---|---|
{parameter_rows}

## Offline evaluation

| Metric | Value |
|---|---:|
{metric_rows}

## Limitations

- The data is synthetic and does not establish real-world model quality.
- Fairness, calibration by subgroup, privacy, and production drift require
  domain-specific evaluation before deployment.
- Promotion approval demonstrates platform policy; it is not a substitute for
  business, legal, or risk review.
"""

    def register_model(
        self,
        *,
        tenant: str,
        model_name: str,
        run_id: str,
        artifact: ModelArtifact,
        dataset_sha256: str,
        code_revision: str,
        parameters: dict[str, Any],
        metrics: dict[str, float],
    ) -> ModelVersion:
        """Persist an immutable artifact and assign the next model version."""

        self._validate_identity(tenant, model_name)
        artifact_text = artifact.to_json()
        artifact_sha256 = sha256_bytes(artifact_text.encode("utf-8"))
        created_at = utc_now()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                """
                SELECT tenant, model_name, status
                FROM runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise NotFoundError(f"run {run_id!r} does not exist")
            if run["tenant"] != tenant or run["model_name"] != model_name:
                raise ConflictError("run identity does not match the model being registered")
            if run["status"] != "running":
                raise ConflictError("only a running pipeline may register a model")

            next_version = connection.execute(
                """
                SELECT COALESCE(MAX(version), 0) + 1
                FROM model_versions WHERE tenant = ? AND model_name = ?
                """,
                (tenant, model_name),
            ).fetchone()[0]
            version_directory = self.artifact_root / tenant / model_name / str(next_version)
            artifact_path = version_directory / "model.json"
            metadata_path = version_directory / "metadata.json"
            model_card_path = version_directory / "MODEL_CARD.md"
            relative_artifact = artifact_path.relative_to(self.state_dir).as_posix()
            relative_card = model_card_path.relative_to(self.state_dir).as_posix()

            metadata = {
                "schema_version": "1",
                "tenant": tenant,
                "model_name": model_name,
                "version": next_version,
                "run_id": run_id,
                "code_revision": code_revision,
                "dataset_sha256": dataset_sha256,
                "artifact_sha256": artifact_sha256,
                "parameters": parameters,
                "metrics": metrics,
                "created_at": created_at,
            }
            atomic_write_text(artifact_path, artifact_text)
            atomic_write_text(metadata_path, canonical_json(metadata) + "\n")
            atomic_write_text(
                model_card_path,
                self._model_card(
                    tenant=tenant,
                    model_name=model_name,
                    version=next_version,
                    run_id=run_id,
                    code_revision=code_revision,
                    dataset_sha256=dataset_sha256,
                    artifact_sha256=artifact_sha256,
                    parameters=parameters,
                    metrics=metrics,
                ),
            )

            connection.execute(
                """
                INSERT INTO models (tenant, name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(tenant, name) DO NOTHING
                """,
                (tenant, model_name, created_at),
            )
            connection.execute(
                """
                INSERT INTO model_versions (
                    tenant, model_name, version, run_id, stage, artifact_path,
                    artifact_sha256, dataset_sha256, code_revision,
                    parameters_json, metrics_json, model_card_path, created_at
                ) VALUES (?, ?, ?, ?, 'registered', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    model_name,
                    next_version,
                    run_id,
                    relative_artifact,
                    artifact_sha256,
                    dataset_sha256,
                    code_revision,
                    canonical_json(parameters),
                    canonical_json(metrics),
                    relative_card,
                    created_at,
                ),
            )
            self._insert_audit(
                connection,
                event_type="model_registered",
                tenant=tenant,
                model_name=model_name,
                version=next_version,
                actor="training-pipeline",
                reason="pipeline completed registration stage",
                payload={"run_id": run_id, "artifact_sha256": artifact_sha256},
            )
            connection.commit()
        return self.get_version(tenant, model_name, int(next_version))

    @staticmethod
    def _row_to_version(row: sqlite3.Row) -> ModelVersion:
        return ModelVersion(
            tenant=row["tenant"],
            model_name=row["model_name"],
            version=int(row["version"]),
            run_id=row["run_id"],
            stage=row["stage"],
            artifact_path=row["artifact_path"],
            artifact_sha256=row["artifact_sha256"],
            dataset_sha256=row["dataset_sha256"],
            code_revision=row["code_revision"],
            parameters=json.loads(row["parameters_json"]),
            metrics={key: float(value) for key, value in json.loads(row["metrics_json"]).items()},
            model_card_path=row["model_card_path"],
            created_at=row["created_at"],
        )

    def get_version(self, tenant: str, model_name: str, version: int) -> ModelVersion:
        self._validate_identity(tenant, model_name)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM model_versions
                WHERE tenant = ? AND model_name = ? AND version = ?
                """,
                (tenant, model_name, version),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"model version {tenant}/{model_name}:{version} does not exist")
        return self._row_to_version(row)

    def list_versions(self, tenant: str, model_name: str) -> list[ModelVersion]:
        self._validate_identity(tenant, model_name)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM model_versions
                WHERE tenant = ? AND model_name = ?
                ORDER BY version DESC
                """,
                (tenant, model_name),
            ).fetchall()
        return [self._row_to_version(row) for row in rows]

    def list_models(self, tenant: str) -> list[dict[str, Any]]:
        validate_resource_name(tenant, "tenant")
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH version_counts AS (
                    SELECT tenant, model_name, COUNT(*) AS version_count
                    FROM model_versions
                    WHERE tenant = ?
                    GROUP BY tenant, model_name
                )
                SELECT
                    models.tenant,
                    models.name,
                    models.created_at,
                    COALESCE(version_counts.version_count, 0) AS version_count,
                    latest.version AS latest_version,
                    latest.stage AS latest_stage,
                    latest.metrics_json AS latest_metrics_json,
                    deployments.stable_version,
                    deployments.canary_version,
                    deployments.canary_weight,
                    deployments.updated_at AS deployment_updated_at
                FROM models
                LEFT JOIN version_counts
                    ON version_counts.tenant = models.tenant
                    AND version_counts.model_name = models.name
                LEFT JOIN model_versions AS latest
                    ON latest.tenant = models.tenant
                    AND latest.model_name = models.name
                    AND latest.version = (
                        SELECT MAX(candidate.version)
                        FROM model_versions AS candidate
                        WHERE candidate.tenant = models.tenant
                        AND candidate.model_name = models.name
                    )
                LEFT JOIN deployments
                    ON deployments.tenant = models.tenant
                    AND deployments.model_name = models.name
                WHERE models.tenant = ?
                ORDER BY models.name
                """,
                (tenant, tenant),
            ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            deployment = None
            if row["stable_version"] is not None:
                deployment = {
                    "stable_version": int(row["stable_version"]),
                    "canary_version": (
                        int(row["canary_version"]) if row["canary_version"] is not None else None
                    ),
                    "canary_weight": int(row["canary_weight"]),
                    "updated_at": row["deployment_updated_at"],
                }
            items.append(
                {
                    "tenant": row["tenant"],
                    "name": row["name"],
                    "created_at": row["created_at"],
                    "version_count": int(row["version_count"]),
                    "latest_version": (
                        int(row["latest_version"]) if row["latest_version"] is not None else None
                    ),
                    "latest_stage": row["latest_stage"],
                    "latest_metrics": (
                        {
                            key: float(value)
                            for key, value in json.loads(row["latest_metrics_json"]).items()
                        }
                        if row["latest_metrics_json"]
                        else None
                    ),
                    "deployment": deployment,
                }
            )
        return items

    def load_artifact(self, tenant: str, model_name: str, version: int) -> ModelArtifact:
        record = self.get_version(tenant, model_name, version)
        artifact_path = self.state_dir / record.artifact_path
        try:
            content = artifact_path.read_bytes()
        except FileNotFoundError as error:
            raise NotFoundError(f"artifact for version {version} is missing") from error
        observed_sha256 = sha256_bytes(content)
        if observed_sha256 != record.artifact_sha256:
            raise ConflictError(
                f"artifact integrity check failed for {tenant}/{model_name}:{version}"
            )
        return ModelArtifact.from_dict(json.loads(content))

    def get_alias(self, tenant: str, model_name: str, alias: str) -> int:
        self._validate_identity(tenant, model_name)
        validate_resource_name(alias, "alias")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT version FROM aliases
                WHERE tenant = ? AND model_name = ? AND alias = ?
                """,
                (tenant, model_name, alias),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"alias {tenant}/{model_name}@{alias} does not exist")
        return int(row["version"])

    def get_deployment(self, tenant: str, model_name: str) -> DeploymentState:
        self._validate_identity(tenant, model_name)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM deployments
                WHERE tenant = ? AND model_name = ?
                """,
                (tenant, model_name),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"deployment {tenant}/{model_name} does not exist")
        return DeploymentState(
            tenant=row["tenant"],
            model_name=row["model_name"],
            stable_version=int(row["stable_version"]),
            canary_version=(
                int(row["canary_version"]) if row["canary_version"] is not None else None
            ),
            canary_weight=int(row["canary_weight"]),
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection,
        *,
        event_type: str,
        tenant: str,
        model_name: str,
        version: int | None,
        actor: str,
        reason: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events (
                event_type, tenant, model_name, version, actor,
                reason, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                tenant,
                model_name,
                version,
                actor,
                reason,
                canonical_json(payload),
                utc_now(),
            ),
        )

    def record_audit(
        self,
        *,
        event_type: str,
        tenant: str,
        model_name: str,
        version: int | None,
        actor: str,
        reason: str,
        payload: dict[str, Any],
    ) -> None:
        self._validate_identity(tenant, model_name)
        with self._connect() as connection:
            self._insert_audit(
                connection,
                event_type=event_type,
                tenant=tenant,
                model_name=model_name,
                version=version,
                actor=actor,
                reason=reason,
                payload=payload,
            )

    def apply_deployment(
        self,
        *,
        tenant: str,
        model_name: str,
        stable_version: int,
        canary_version: int | None,
        canary_weight: int,
        action: str,
        actor: str,
        reason: str,
        payload: dict[str, Any],
    ) -> DeploymentState:
        """Atomically update deployment state, aliases, stages, history, and audit."""

        self._validate_identity(tenant, model_name)
        if not 0 <= canary_weight <= 100:
            raise ConflictError("canary_weight must be between 0 and 100")
        if canary_version is None and canary_weight != 0:
            raise ConflictError("canary_weight must be zero without a canary version")
        if canary_version == stable_version:
            raise ConflictError("stable and canary versions must differ")
        now = utc_now()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            versions = [stable_version]
            if canary_version is not None:
                versions.append(canary_version)
            placeholders = ",".join("?" for _ in versions)
            rows = connection.execute(
                f"""
                SELECT version FROM model_versions
                WHERE tenant = ? AND model_name = ? AND version IN ({placeholders})
                """,
                (tenant, model_name, *versions),
            ).fetchall()
            found = {int(row["version"]) for row in rows}
            if found != set(versions):
                missing = sorted(set(versions) - found)
                raise NotFoundError(f"deployment references missing versions: {missing}")

            connection.execute(
                """
                INSERT INTO deployments (
                    tenant, model_name, stable_version, canary_version,
                    canary_weight, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant, model_name) DO UPDATE SET
                    stable_version = excluded.stable_version,
                    canary_version = excluded.canary_version,
                    canary_weight = excluded.canary_weight,
                    updated_at = excluded.updated_at
                """,
                (
                    tenant,
                    model_name,
                    stable_version,
                    canary_version,
                    canary_weight,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE model_versions SET stage = 'registered'
                WHERE tenant = ? AND model_name = ?
                """,
                (tenant, model_name),
            )
            connection.execute(
                """
                UPDATE model_versions SET stage = 'production'
                WHERE tenant = ? AND model_name = ? AND version = ?
                """,
                (tenant, model_name, stable_version),
            )
            if canary_version is not None:
                connection.execute(
                    """
                    UPDATE model_versions SET stage = 'canary'
                    WHERE tenant = ? AND model_name = ? AND version = ?
                    """,
                    (tenant, model_name, canary_version),
                )

            connection.execute(
                """
                DELETE FROM aliases
                WHERE tenant = ? AND model_name = ?
                  AND alias IN ('production', 'champion', 'challenger')
                """,
                (tenant, model_name),
            )
            for alias, version in (
                ("production", stable_version),
                ("champion", stable_version),
                ("challenger", canary_version),
            ):
                if version is None:
                    continue
                connection.execute(
                    """
                    INSERT INTO aliases (
                        tenant, model_name, alias, version, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (tenant, model_name, alias, version, now),
                )

            connection.execute(
                """
                INSERT INTO deployment_history (
                    tenant, model_name, action, stable_version, canary_version,
                    canary_weight, actor, reason, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    model_name,
                    action,
                    stable_version,
                    canary_version,
                    canary_weight,
                    actor,
                    reason,
                    canonical_json(payload),
                    now,
                ),
            )
            self._insert_audit(
                connection,
                event_type=action,
                tenant=tenant,
                model_name=model_name,
                version=canary_version or stable_version,
                actor=actor,
                reason=reason,
                payload={
                    **payload,
                    "stable_version": stable_version,
                    "canary_version": canary_version,
                    "canary_weight": canary_weight,
                },
            )
            connection.commit()
        return self.get_deployment(tenant, model_name)

    def list_audit_events(
        self, tenant: str, model_name: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        self._validate_identity(tenant, model_name)
        bounded_limit = max(1, min(limit, 500))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM audit_events
                WHERE tenant = ? AND model_name = ?
                ORDER BY id DESC LIMIT ?
                """,
                (tenant, model_name, bounded_limit),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "event_type": row["event_type"],
                "tenant": row["tenant"],
                "model_name": row["model_name"],
                "version": (int(row["version"]) if row["version"] is not None else None),
                "actor": row["actor"],
                "reason": row["reason"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_deployment_history(
        self, tenant: str, model_name: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        self._validate_identity(tenant, model_name)
        bounded_limit = max(1, min(limit, 500))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM deployment_history
                WHERE tenant = ? AND model_name = ?
                ORDER BY id DESC LIMIT ?
                """,
                (tenant, model_name, bounded_limit),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "action": row["action"],
                "stable_version": int(row["stable_version"]),
                "canary_version": (
                    int(row["canary_version"]) if row["canary_version"] is not None else None
                ),
                "canary_weight": int(row["canary_weight"]),
                "actor": row["actor"],
                "reason": row["reason"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
