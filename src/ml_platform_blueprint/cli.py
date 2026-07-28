"""Command-line interface for local lifecycle demos and operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import Settings
from .data import FEATURE_NAMES
from .domain import CanaryObservation, GateRejectedError, PlatformError
from .service import PlatformService, TrainingParameters
from .utils import InvalidResourceName


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _settings(args: argparse.Namespace) -> Settings:
    defaults = Settings.from_env()
    return Settings(
        state_dir=Path(args.state_dir),
        allowed_tenants=defaults.allowed_tenants,
        code_revision=defaults.code_revision,
        mlflow_tracking_uri=defaults.mlflow_tracking_uri,
        mlflow_experiment=defaults.mlflow_experiment,
        environment=defaults.environment,
    )


def _training_parameters(args: argparse.Namespace) -> TrainingParameters:
    return TrainingParameters(
        samples=args.samples,
        data_seed=args.data_seed,
        split_seed=args.split_seed,
        test_fraction=args.test_fraction,
        learning_rate=args.learning_rate,
        epochs=args.epochs,
        l2=args.l2,
        decision_threshold=args.decision_threshold,
    )


def _sample_instance() -> dict[str, float]:
    values = (12.0, 90.0, 2.0, 55.0, 1.0, 1.0)
    return dict(zip(FEATURE_NAMES, values, strict=True))


def _run_demo(service: PlatformService, tenant: str, model_name: str) -> dict[str, Any]:
    baseline = service.train_and_register(
        tenant=tenant,
        model_name=model_name,
        parameters=TrainingParameters(),
    )
    baseline_version = int(baseline["model_version"]["version"])
    initial = service.promote(
        tenant=tenant,
        model_name=model_name,
        version=baseline_version,
        canary_weight=10,
        actor="local-demo",
        reason="deploy reproducible baseline",
    )

    candidate = service.train_and_register(
        tenant=tenant,
        model_name=model_name,
        parameters=TrainingParameters(learning_rate=0.10, epochs=900, l2=0.005),
    )
    candidate_version = int(candidate["model_version"]["version"])
    canary = service.promote(
        tenant=tenant,
        model_name=model_name,
        version=candidate_version,
        canary_weight=20,
        actor="local-demo",
        reason="candidate passed offline quality policy",
    )

    routed: dict[str, int] = {"stable": 0, "canary": 0}
    example_predictions: list[dict[str, Any]] = []
    for index in range(30):
        prediction = service.predict(
            tenant=tenant,
            model_name=model_name,
            instances=[_sample_instance()],
            request_id=f"demo-request-{index}",
        )
        routed[prediction["route"]] += 1
        if len(example_predictions) < 3:
            example_predictions.append(prediction)

    finalized = service.finalize_canary(
        tenant=tenant,
        model_name=model_name,
        observation=CanaryObservation(
            stable_error_rate=0.010,
            canary_error_rate=0.012,
            stable_p95_ms=35.0,
            canary_p95_ms=37.0,
            sample_size=500,
        ),
        actor="local-demo",
        reason="candidate passed online SLI guardrails",
    )
    return {
        "baseline": baseline,
        "initial_deployment": initial,
        "candidate": candidate,
        "canary_deployment": canary,
        "canary_routing_sample": routed,
        "example_predictions": example_predictions,
        "finalized_deployment": finalized,
        "audit_events": service.registry.list_audit_events(tenant, model_name),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ml-platform",
        description="Operate the ML Platform Blueprint reference plane.",
    )
    parser.add_argument(
        "--state-dir",
        default=".ml-platform",
        help="Registry and artifact state directory (default: .ml-platform)",
    )
    parser.add_argument("--tenant", default="team-a")
    parser.add_argument("--model", default="churn-classifier")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the local registry.")

    train = subparsers.add_parser("train", help="Train, evaluate, and register a model.")
    train.add_argument("--samples", type=int, default=800)
    train.add_argument("--data-seed", type=int, default=42)
    train.add_argument("--split-seed", type=int, default=42)
    train.add_argument("--test-fraction", type=float, default=0.2)
    train.add_argument("--learning-rate", type=float, default=0.12)
    train.add_argument("--epochs", type=int, default=700)
    train.add_argument("--l2", type=float, default=0.01)
    train.add_argument("--decision-threshold", type=float, default=0.5)

    promote = subparsers.add_parser(
        "promote", help="Apply the offline gate and start a deployment."
    )
    promote.add_argument("--version", type=int, required=True)
    promote.add_argument("--canary-weight", type=int, default=10)
    promote.add_argument("--actor", default="local-operator")
    promote.add_argument("--reason", default="operator-approved promotion")

    predict = subparsers.add_parser("predict", help="Run reference inference.")
    predict.add_argument(
        "--instance",
        help="JSON object with model features; defaults to a built-in example",
    )
    predict.add_argument("--request-id")

    finalize = subparsers.add_parser(
        "finalize", help="Evaluate online SLIs and finish an active canary."
    )
    finalize.add_argument("--stable-error-rate", type=float, required=True)
    finalize.add_argument("--canary-error-rate", type=float, required=True)
    finalize.add_argument("--stable-p95-ms", type=float, required=True)
    finalize.add_argument("--canary-p95-ms", type=float, required=True)
    finalize.add_argument("--sample-size", type=int, required=True)
    finalize.add_argument("--actor", default="local-operator")
    finalize.add_argument("--reason", default="online SLI review")

    rollback = subparsers.add_parser(
        "rollback", help="Discard a canary or roll stable traffic to a version."
    )
    rollback.add_argument("--target-version", type=int)
    rollback.add_argument("--actor", default="local-operator")
    rollback.add_argument("--reason", default="operator-requested rollback")

    subparsers.add_parser("status", help="Show current deployment and versions.")
    subparsers.add_parser("audit", help="Show the model audit trail.")
    subparsers.add_parser("demo", help="Run the complete local lifecycle.")

    serve = subparsers.add_parser("serve", help="Start the HTTP API.")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument(
        "--no-access-log",
        action="store_true",
        help="Disable per-request access logs, for example during load tests.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = _settings(args)
    try:
        if args.command == "serve":
            import uvicorn

            from .api import create_app

            uvicorn.run(
                create_app(settings),
                host=args.host,
                port=args.port,
                access_log=not args.no_access_log,
            )
            return 0

        service = PlatformService(settings)
        tenant = str(args.tenant)
        model_name = str(args.model)

        if args.command == "init":
            _print(
                {
                    "status": "initialized",
                    "state_dir": str(service.registry.state_dir),
                    "tenants": list(settings.allowed_tenants),
                }
            )
        elif args.command == "train":
            _print(
                service.train_and_register(
                    tenant=tenant,
                    model_name=model_name,
                    parameters=_training_parameters(args),
                )
            )
        elif args.command == "promote":
            _print(
                service.promote(
                    tenant=tenant,
                    model_name=model_name,
                    version=args.version,
                    canary_weight=args.canary_weight,
                    actor=args.actor,
                    reason=args.reason,
                )
            )
        elif args.command == "predict":
            instance = json.loads(args.instance) if args.instance else _sample_instance()
            if not isinstance(instance, dict):
                parser.error("--instance must be a JSON object")
            _print(
                service.predict(
                    tenant=tenant,
                    model_name=model_name,
                    instances=[instance],
                    request_id=args.request_id,
                )
            )
        elif args.command == "finalize":
            _print(
                service.finalize_canary(
                    tenant=tenant,
                    model_name=model_name,
                    observation=CanaryObservation(
                        stable_error_rate=args.stable_error_rate,
                        canary_error_rate=args.canary_error_rate,
                        stable_p95_ms=args.stable_p95_ms,
                        canary_p95_ms=args.canary_p95_ms,
                        sample_size=args.sample_size,
                    ),
                    actor=args.actor,
                    reason=args.reason,
                )
            )
        elif args.command == "rollback":
            _print(
                service.rollback(
                    tenant=tenant,
                    model_name=model_name,
                    target_version=args.target_version,
                    actor=args.actor,
                    reason=args.reason,
                )
            )
        elif args.command == "status":
            deployment: dict[str, Any] | None
            try:
                deployment = service.registry.get_deployment(tenant, model_name).to_dict()
            except PlatformError:
                deployment = None
            _print(
                {
                    "deployment": deployment,
                    "versions": [
                        version.to_dict()
                        for version in service.registry.list_versions(tenant, model_name)
                    ],
                }
            )
        elif args.command == "audit":
            _print({"items": service.registry.list_audit_events(tenant, model_name)})
        elif args.command == "demo":
            _print(_run_demo(service, tenant, model_name))
        else:
            parser.error(f"unsupported command: {args.command}")
        return 0
    except GateRejectedError as error:
        _print(
            {
                "error": error.code,
                "message": str(error),
                "decision": error.decision.to_dict(),
            }
        )
        return 2
    except (
        PlatformError,
        InvalidResourceName,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        _print(
            {
                "error": getattr(error, "code", "invalid_input"),
                "message": str(error),
            }
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
