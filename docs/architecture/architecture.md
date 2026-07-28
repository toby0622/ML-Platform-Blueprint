# Architecture

## Goals and quality attributes

ML Platform Blueprint is an internal platform product for data scientists and
ML engineers. It optimizes for:

1. reproducible and traceable model changes;
2. safe, observable delivery rather than raw deployment speed;
3. tenant self-service within explicit resource and security boundaries;
4. a laptop-sized development loop with a credible Kubernetes production path;
5. replaceable components connected by stable artifact and API contracts.

It does not optimize the classifier itself, implement a general-purpose feature
store, or pretend a home lab is a globally available production service.

## System context

```mermaid
flowchart LR
  DS["Data scientist"] -->|"submit run / inspect lineage"| Platform["ML platform"]
  PE["Platform engineer"] -->|"policy / capacity / GitOps"| Platform
  CI["CI identity"] -->|"publish signed images"| Platform
  Platform --> Git["Git + OCI registry"]
  Platform --> Store["Metadata DB + object store"]
  Platform --> K8s["Kubernetes APIs"]
  Platform --> Obs["Telemetry backend"]
  App["Application team"] -->|"prediction / chat"| Platform
```

Trust boundaries are the CI identity, cluster API, tenant namespaces, metadata
plane, artifact store, and external inference clients.

## Container and plane view

```mermaid
flowchart TB
  subgraph Entry["Developer entry points"]
    CLI["ml-platform CLI"]
    API["FastAPI self-service API"]
    Git["Git pull request"]
  end

  subgraph Training["Training / pipeline plane"]
    KFP["Kubeflow Pipelines"]
    Validate["schema + statistical validation"]
    Train["deterministic training"]
    Evaluate["offline metrics + policy"]
    Register["registration component"]
    KFP --> Validate --> Train --> Evaluate --> Register
  end

  subgraph Metadata["Metadata / artifact plane"]
    Local["SQLite + local artifacts<br/>reference profile"]
    MLflow["MLflow workspaces / registry"]
    PG["PostgreSQL"]
    S3["S3-compatible object store"]
    MLflow --> PG
    MLflow --> S3
  end

  subgraph Serving["Serving plane"]
    Router["promotion + deterministic canary router"]
    Custom["KServe-compatible predictive runtime"]
    VLLM["KServe Hugging Face / vLLM runtime"]
    Router --> Custom
    Router --> VLLM
  end

  subgraph Scheduling["Scheduling and accelerator plane"]
    Kueue["Kueue queues / cohorts / priority"]
    Quota["ResourceQuota + LimitRange"]
    GPU["GPU Operator / Device Plugin"]
    DCGM["DCGM Exporter"]
    GPU --> DCGM
  end

  subgraph Governance["Governance"]
    RBAC["RBAC / ServiceAccounts"]
    Net["default-deny NetworkPolicy"]
    Admission["Pod Security + Kyverno"]
    Supply["SBOM + provenance + Cosign"]
  end

  subgraph Telemetry["Observability"]
    Prom["Prometheus + alerts"]
    Grafana["Grafana"]
    OTel["OpenTelemetry"]
    Prom --> Grafana
  end

  CLI --> API
  Git --> KFP
  API --> Local
  KFP --> MLflow
  Register --> MLflow
  Local --> Router
  MLflow --> Serving
  Kueue -. admission .-> KFP
  Kueue -. admission .-> Serving
  Quota -. hard ceiling .-> KFP
  GPU -. GPU resource .-> VLLM
  Serving --> Prom
  Training --> Prom
  DCGM --> Prom
  Governance -. policy .-> Training
  Governance -. policy .-> Serving
```

## Model lifecycle sequence

```mermaid
sequenceDiagram
  actor User
  participant API as Platform API / KFP
  participant Data as Data validator
  participant Train as Trainer
  participant Registry as Registry + artifact store
  participant Gate as Promotion controller
  participant Serve as Stable/canary serving
  participant Metrics as Prometheus

  User->>API: submit parameters + tenant + model
  API->>Data: generate/read versioned data
  Data-->>API: schema result + SHA-256
  API->>Train: deterministic split and training
  Train-->>API: model.json + offline metrics
  API->>Registry: immutable artifact + lineage + model card
  Registry-->>API: assigned version
  User->>Gate: promote(version, actor, reason)
  Gate->>Registry: read offline metrics
  alt offline gate fails
    Gate->>Registry: audit rejection
    Gate-->>User: 422 with failed checks
  else first healthy version
    Gate->>Serve: 100% stable
  else later healthy version
    Gate->>Serve: weighted deterministic canary
    Serve->>Metrics: route, error, latency, version
    alt online gate passes
      Gate->>Serve: candidate becomes stable
    else online regression
      Gate->>Serve: atomically remove canary
      Gate->>Registry: audit automatic rollback
    end
  end
```

## Artifact and lineage contract

The reference artifact is canonical JSON rather than pickle. Loading it does
not execute code. Its SHA-256 is verified before inference.

```text
tenant/model/version/
├── model.json
├── metadata.json
└── MODEL_CARD.md
```

`metadata.json` connects:

```text
model version
  -> pipeline run ID
  -> code revision
  -> dataset SHA-256
  -> parameters
  -> offline metrics
  -> artifact SHA-256
```

The KFP path carries typed Dataset, Model, Metrics, and registration artifacts.
The API mirror records run-scoped parameters, metrics, and tags in MLflow. The
KFP registration component additionally logs the model artifact and creates the
tenant-qualified registered model version (`<tenant>--<model>`).

## Tenancy

Tenant identity appears in the API path, registry key, Kubernetes namespace,
Kueue queue, metrics labels, and audit event. Defense in depth:

| Boundary | Mechanism |
|---|---|
| API | allowlist and optional `X-Tenant-Id` consistency check |
| Kubernetes API | namespace Role/RoleBinding, dedicated ServiceAccounts |
| Compute | ResourceQuota, LimitRange, Kueue nominal/borrow limits |
| Network | default deny; explicit DNS, platform, gateway, and monitoring flows |
| Admission | Pod Security restricted plus Kyverno workload rules |
| Supply chain | lab tags for iteration; production digest policy plus keyless signature verification |
| Object storage | EKS Pod Identity; pipeline read/write and serving read-only within `tenants/<tenant>/` |
| Metadata | tenant tags and naming for logical separation; separate MLflow deployments and artifact IAM for hard isolation |

Kueue provides admission control and fair borrowing. ResourceQuota remains the
hard namespace ceiling even if queue policy is misconfigured.

## Availability and consistency

- The local registry uses SQLite transactions, WAL, immutable files, and atomic
  file replacement. It is a single-replica reference profile.
- Deployment state, aliases, stages, history, and audit are changed in one
  database transaction.
- Request routing hashes a request ID into 100 buckets. Retries with the same ID
  reach the same revision, simplifying canary comparisons.
- KServe owns Kubernetes revision readiness and traffic shifting in the cluster
  profile.
- MLflow production metadata uses PostgreSQL; artifacts use versioned object
  storage.

## Environment profiles

| Profile | Purpose | Metadata/artifacts | Compute |
|---|---|---|---|
| Python | fastest deterministic lifecycle tests | SQLite/filesystem | local process |
| Compose | integrated metadata and telemetry | MLflow + PostgreSQL + MinIO | Docker |
| RTX workstation | vLLM scenario and GPU telemetry evidence | Hugging Face cache + hashed local results | one container-visible, desktop-shared RTX 4080 SUPER through WSL 2 Compose |
| kind | tenancy, policy, queue, GitOps, KServe control plane | lab PVC or external | CPU Kubernetes |
| AWS | production design | RDS + KMS/S3 | EKS CPU and optional A10G |
| GPU lab | inference evidence | chosen object store | real NVIDIA node |

The RTX workstation is a direct serving data-plane profile, not a substitute
for the Kubernetes GPU control plane. It validates CUDA container access,
vLLM behavior, OpenAI-compatible traffic, and host-visible GPU telemetry.
GPU Operator, DCGM, Kueue admission, KServe reconciliation, autoscaling, and
node-failure behavior remain native-Linux cluster validations.

## Failure domains

| Failure | Expected behavior |
|---|---|
| Bad offline model | promotion is rejected; no traffic changes |
| Bad canary | online gate clears canary and retains stable |
| Artifact tampering | SHA mismatch fails closed before model load |
| MLflow unavailable | new registration is blocked; existing serving remains independent |
| Object store unavailable | new pods may fail readiness; existing loaded models remain available |
| GPU unavailable | workload stays Pending; queue and DCGM alerts identify resource vs device failure |
| Tenant burst | Kueue queues work; ResourceQuota prevents unbounded allocation |
| GitOps drift | Argo CD detects and self-heals first-party resources |

Operational details are in [the runbooks](../../runbooks/).
