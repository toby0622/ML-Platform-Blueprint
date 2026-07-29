"""FastAPI control and reference serving plane."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .config import Settings
from .domain import (
    CanaryObservation,
    ConflictError,
    GateRejectedError,
    NotFoundError,
    PlatformError,
    TenantAccessError,
    ValidationError,
)
from .service import PlatformService, TrainingParameters
from .tracing import configure_tracing, tracing_lifespan
from .utils import InvalidResourceName


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrainingRequest(StrictRequest):
    samples: int = Field(default=800, ge=100, le=100_000)
    data_seed: int = 42
    split_seed: int = 42
    test_fraction: float = Field(default=0.2, ge=0.1, le=0.5)
    learning_rate: float = Field(default=0.12, gt=0, le=1)
    epochs: int = Field(default=700, ge=10, le=20_000)
    l2: float = Field(default=0.01, ge=0, le=10)
    decision_threshold: float = Field(default=0.5, gt=0, lt=1)


class PromotionRequest(StrictRequest):
    canary_weight: int = Field(default=10, ge=1, le=50)
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=500)


class CanaryObservationRequest(StrictRequest):
    stable_error_rate: float = Field(ge=0, le=1)
    canary_error_rate: float = Field(ge=0, le=1)
    stable_p95_ms: float = Field(gt=0)
    canary_p95_ms: float = Field(gt=0)
    sample_size: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=500)


class RollbackRequest(StrictRequest):
    target_version: int | None = Field(default=None, ge=1)
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=500)


class PredictionRequest(StrictRequest):
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    instances: list[dict[str, float]] = Field(min_length=1, max_length=1000)


def _status_for(error: PlatformError) -> int:
    if isinstance(error, NotFoundError):
        return 404
    if isinstance(error, ConflictError):
        return 409
    if isinstance(error, TenantAccessError):
        return 403
    if isinstance(error, (ValidationError, GateRejectedError)):
        return 422
    return 500


def create_app(
    settings: Settings | None = None,
    service: PlatformService | None = None,
    *,
    span_exporter: Any | None = None,
) -> FastAPI:
    selected_settings = settings or Settings.from_env()
    selected_service = service or PlatformService(selected_settings)
    application = FastAPI(
        title="ML Platform Blueprint API",
        version=__version__,
        description=(
            "Self-service training, lineage, promotion, canary, rollback, and "
            "reference inference plane."
        ),
        lifespan=tracing_lifespan,
    )
    application.state.service = selected_service

    @application.exception_handler(PlatformError)
    async def handle_platform_error(_request: Request, error: PlatformError) -> JSONResponse:
        details: dict[str, Any] = {}
        if isinstance(error, GateRejectedError):
            details["decision"] = error.decision.to_dict()
        return JSONResponse(
            status_code=_status_for(error),
            content={
                "error": {
                    "code": error.code,
                    "message": str(error),
                    "details": details,
                }
            },
        )

    @application.exception_handler(InvalidResourceName)
    async def handle_resource_name(_request: Request, error: InvalidResourceName) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_resource_name",
                    "message": str(error),
                    "details": {},
                }
            },
        )

    def verify_tenant_header(
        tenant: str,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> None:
        selected_service.authorize_tenant(tenant)
        if x_tenant_id is not None and x_tenant_id != tenant:
            raise TenantAccessError("X-Tenant-Id does not match the tenant in the request path")

    @application.get("/", tags=["system"])
    def root() -> dict[str, Any]:
        return {
            "name": "ml-platform-blueprint",
            "version": __version__,
            "environment": selected_settings.environment,
            "allowed_tenants": list(selected_settings.allowed_tenants),
            "links": {
                "openapi": "/openapi.json",
                "docs": "/docs",
                "health": "/healthz",
                "metrics": "/metrics",
            },
        }

    @application.get("/healthz", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz", tags=["system"])
    def readiness() -> JSONResponse:
        ready = selected_service.registry.check_ready()
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "not_ready"},
        )

    @application.get("/metrics", response_class=PlainTextResponse, tags=["system"])
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(
            selected_service.telemetry.render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @application.get("/v1/tenants", tags=["catalog"])
    def list_tenants() -> dict[str, Any]:
        return {"items": [{"name": tenant} for tenant in selected_settings.allowed_tenants]}

    @application.get("/v1/tenants/{tenant}/overview", tags=["catalog"])
    def tenant_overview(
        tenant: str,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        models = selected_service.registry.list_models(tenant)
        recent_runs = selected_service.registry.list_runs(tenant, limit=8)
        return {
            "tenant": tenant,
            "environment": selected_settings.environment,
            "summary": {
                "models": len(models),
                "versions": sum(int(model["version_count"]) for model in models),
                "active_canaries": sum(
                    1
                    for model in models
                    if model["deployment"] is not None
                    and model["deployment"]["canary_version"] is not None
                ),
                "recent_runs": len(recent_runs),
            },
            "models": models,
            "recent_runs": recent_runs,
        }

    @application.get("/v1/tenants/{tenant}/models", tags=["catalog"])
    def list_models(
        tenant: str,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        return {"items": selected_service.registry.list_models(tenant)}

    @application.get("/v1/tenants/{tenant}/runs", tags=["training"])
    def list_runs(
        tenant: str,
        model_name: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        return {
            "items": selected_service.registry.list_runs(
                tenant,
                model_name=model_name,
                limit=limit,
            )
        }

    @application.get("/v1/tenants/{tenant}/runs/{run_id}", tags=["training"])
    def get_tenant_run(
        tenant: str,
        run_id: str,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        run = selected_service.registry.get_run(run_id)
        if run["tenant"] != tenant:
            raise NotFoundError(f"run {run_id!r} does not exist for tenant {tenant!r}")
        return run

    @application.post(
        "/v1/tenants/{tenant}/models/{model_name}/runs",
        status_code=201,
        tags=["training"],
    )
    def train(
        tenant: str,
        model_name: str,
        body: TrainingRequest,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        return selected_service.train_and_register(
            tenant=tenant,
            model_name=model_name,
            parameters=TrainingParameters(**body.model_dump()),
        )

    @application.get("/v1/runs/{run_id}", tags=["training"])
    def get_run(run_id: str) -> dict[str, Any]:
        return selected_service.registry.get_run(run_id)

    @application.get(
        "/v1/tenants/{tenant}/models/{model_name}/versions",
        tags=["registry"],
    )
    def list_versions(
        tenant: str,
        model_name: str,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        versions = selected_service.registry.list_versions(tenant, model_name)
        return {"items": [version.to_dict() for version in versions]}

    @application.get(
        "/v1/tenants/{tenant}/models/{model_name}/versions/{version}",
        tags=["registry"],
    )
    def get_version(
        tenant: str,
        model_name: str,
        version: int,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        return selected_service.registry.get_version(tenant, model_name, version).to_dict()

    @application.post(
        "/v1/tenants/{tenant}/models/{model_name}/versions/{version}/promotion",
        tags=["deployment"],
    )
    def promote(
        tenant: str,
        model_name: str,
        version: int,
        body: PromotionRequest,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        return selected_service.promote(
            tenant=tenant,
            model_name=model_name,
            version=version,
            canary_weight=body.canary_weight,
            actor=body.actor,
            reason=body.reason,
        )

    @application.get(
        "/v1/tenants/{tenant}/models/{model_name}/deployment",
        tags=["deployment"],
    )
    def get_deployment(
        tenant: str,
        model_name: str,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        return selected_service.registry.get_deployment(tenant, model_name).to_dict()

    @application.get(
        "/v1/tenants/{tenant}/models/{model_name}/deployment/history",
        tags=["deployment"],
    )
    def deployment_history(
        tenant: str,
        model_name: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        return {
            "items": selected_service.registry.list_deployment_history(
                tenant,
                model_name,
                limit,
            )
        }

    @application.post(
        "/v1/tenants/{tenant}/models/{model_name}/deployment/finalize",
        tags=["deployment"],
    )
    def finalize_canary(
        tenant: str,
        model_name: str,
        body: CanaryObservationRequest,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        return selected_service.finalize_canary(
            tenant=tenant,
            model_name=model_name,
            observation=CanaryObservation(
                stable_error_rate=body.stable_error_rate,
                canary_error_rate=body.canary_error_rate,
                stable_p95_ms=body.stable_p95_ms,
                canary_p95_ms=body.canary_p95_ms,
                sample_size=body.sample_size,
            ),
            actor=body.actor,
            reason=body.reason,
        )

    @application.post(
        "/v1/tenants/{tenant}/models/{model_name}/deployment/rollback",
        tags=["deployment"],
    )
    def rollback(
        tenant: str,
        model_name: str,
        body: RollbackRequest,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        return selected_service.rollback(
            tenant=tenant,
            model_name=model_name,
            target_version=body.target_version,
            actor=body.actor,
            reason=body.reason,
        )

    @application.post(
        "/v1/tenants/{tenant}/models/{model_name}/predict",
        tags=["serving"],
    )
    def predict(
        tenant: str,
        model_name: str,
        body: PredictionRequest,
        x_tenant_id: Annotated[str | None, Header()] = None,
        x_request_id: Annotated[
            str | None,
            Header(min_length=1, max_length=128),
        ] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        return selected_service.predict(
            tenant=tenant,
            model_name=model_name,
            request_id=body.request_id or x_request_id,
            instances=body.instances,
        )

    @application.get(
        "/v1/tenants/{tenant}/models/{model_name}/audit",
        tags=["governance"],
    )
    def audit(
        tenant: str,
        model_name: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_tenant_header(tenant, x_tenant_id)
        return {"items": selected_service.registry.list_audit_events(tenant, model_name, limit)}

    configure_tracing(
        application,
        selected_settings,
        span_exporter=span_exporter,
    )
    return application


app = create_app()
