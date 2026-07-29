"""Optional OpenTelemetry instrumentation for the HTTP control plane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol, cast

from fastapi import FastAPI

from .config import Settings


class _TracerProvider(Protocol):
    def shutdown(self) -> None: ...


@asynccontextmanager
async def tracing_lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Shut down the configured tracing provider with the ASGI application."""

    try:
        yield
    finally:
        provider = cast(
            _TracerProvider | None,
            getattr(application.state, "tracer_provider", None),
        )
        if provider is not None:
            provider.shutdown()


def configure_tracing(
    application: FastAPI,
    settings: Settings,
    *,
    span_exporter: Any | None = None,
) -> _TracerProvider | None:
    """Instrument an application when an OTLP traces endpoint is configured."""

    if settings.otel_traces_endpoint is None:
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as error:
        raise RuntimeError(
            "OTLP tracing is configured but the otel extra is not installed; "
            "run `pip install -e .[otel]`"
        ) from error

    exporter = span_exporter or OTLPSpanExporter(endpoint=settings.otel_traces_endpoint)
    provider = TracerProvider(
        resource=Resource.create(
            {
                SERVICE_NAME: settings.otel_service_name,
                "deployment.environment.name": settings.environment,
                "service.version": application.version,
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    FastAPIInstrumentor.instrument_app(
        application,
        tracer_provider=provider,
        excluded_urls="healthz,readyz,metrics",
    )
    application.state.tracer_provider = provider
    return provider
