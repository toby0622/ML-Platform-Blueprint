# Observability

The observability contract has four layers:

| Layer | Primary signals |
|---|---|
| Service | request rate, errors, availability, latency |
| Model | version, stable/canary traffic, prediction distribution, drift hooks |
| Pipeline | run status, duration, quality-gate decision, queue wait |
| GPU | utilization, framebuffer memory, power, temperature, XID errors |

Compose provisions Prometheus and Grafana using the files in this directory.
Kubernetes uses ServiceMonitor resources plus Kueue and DCGM exporters.
The platform API emits OTLP/HTTP spans when
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is set. Compose and the Kubernetes
Kustomization run a two-replica OpenTelemetry Collector gateway, exclude
health/readiness/metrics probes from tracing, batch and retry exports, and
forward traces to MLflow's OTLP endpoint. The gateway also writes a basic
debug stream so delivery failures remain diagnosable.

Render the Kubernetes gateway without applying it:

```bash
kubectl kustomize observability/opentelemetry
```

The gateway configuration is intentionally traces-only. Add metrics or logs
pipelines only after defining cardinality, retention, and tenant-boundary
contracts.

The example prediction-availability objective is 99.5% over 30 days. Fast and
slow multi-window burn alerts use the corresponding 0.5% error budget. These
remain demonstration defaults; tune the objective and windows from actual
traffic, caller expectations, and incident history.
