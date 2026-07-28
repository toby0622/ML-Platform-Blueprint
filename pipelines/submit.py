"""Submit the compiled lifecycle pipeline with tenant-bound runtime identity."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kfp import Client

from ml_platform_blueprint.utils import InvalidResourceName, validate_resource_name

S3_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


@dataclass(frozen=True, slots=True)
class Submission:
    """Values that bind a KFP run to one tenant identity and artifact prefix."""

    namespace: str
    service_account: str
    pipeline_root: str
    arguments: dict[str, Any]


def _validate_bucket(value: str) -> str:
    if not S3_BUCKET.fullmatch(value) or ".." in value:
        raise ValueError("artifact bucket must be a valid lower-case S3 bucket name")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError("artifact bucket must not be formatted as an IP address")


def build_submission(
    *,
    tenant: str,
    model_name: str,
    artifact_bucket: str,
    code_revision: str,
    tracking_uri: str,
) -> Submission:
    """Build an auditable run configuration without contacting KFP."""

    try:
        selected_tenant = validate_resource_name(tenant, field="tenant")
        selected_model = validate_resource_name(model_name, field="model_name")
    except InvalidResourceName as error:
        raise ValueError(str(error)) from error
    selected_bucket = _validate_bucket(artifact_bucket)
    if not code_revision.strip():
        raise ValueError("code revision must not be empty")
    if not tracking_uri.startswith(("http://", "https://")):
        raise ValueError("tracking URI must use HTTP or HTTPS")

    return Submission(
        namespace=selected_tenant,
        service_account="ml-developer",
        pipeline_root=f"s3://{selected_bucket}/tenants/{selected_tenant}/pipelines",
        arguments={
            "tenant": selected_tenant,
            "model_name": selected_model,
            "tracking_uri": tracking_uri,
            "code_revision": code_revision,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Submit a tenant-scoped ML Platform Blueprint KFP run."
    )
    parser.add_argument("--host", help="KFP API endpoint; omit for in-cluster discovery")
    parser.add_argument("--pipeline-file", default="pipeline.yaml")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--model", default="churn-classifier")
    parser.add_argument("--artifact-bucket", required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument(
        "--tracking-uri",
        default="http://mlflow.ml-platform-system.svc.cluster.local:5000",
    )
    parser.add_argument("--experiment", default="ml-platform-blueprint")
    parser.add_argument("--run-name")
    args = parser.parse_args()

    pipeline_file = Path(args.pipeline_file)
    if not pipeline_file.is_file():
        parser.error(f"compiled pipeline does not exist: {pipeline_file}")
    try:
        submission = build_submission(
            tenant=args.tenant,
            model_name=args.model,
            artifact_bucket=args.artifact_bucket,
            code_revision=args.code_revision,
            tracking_uri=args.tracking_uri,
        )
    except ValueError as error:
        parser.error(str(error))

    client = Client(host=args.host) if args.host else Client()
    result = client.create_run_from_pipeline_package(
        pipeline_file=str(pipeline_file),
        arguments=submission.arguments,
        run_name=args.run_name,
        experiment_name=args.experiment,
        namespace=submission.namespace,
        pipeline_root=submission.pipeline_root,
        service_account=submission.service_account,
    )
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "namespace": submission.namespace,
                "service_account": submission.service_account,
                "pipeline_root": submission.pipeline_root,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
