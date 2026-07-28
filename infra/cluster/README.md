# Local Kubernetes cluster

The local profile uses a three-node kind cluster on Kubernetes 1.34. It is a
CPU-only integration environment for tenancy, queues, policy, GitOps,
observability, and predictive serving control-plane tests.

Prerequisites: Docker, kind, kubectl, and Helm.

PowerShell:

```powershell
./scripts/bootstrap-kind.ps1
```

Bash:

```bash
./scripts/bootstrap-kind.sh
```

Kubeflow Pipelines is intentionally opt-in because it is resource-heavy:

```powershell
./scripts/bootstrap-kind.ps1 -WithKfp
```

The GPU Operator and vLLM manifests require a real NVIDIA node and are not
installed by the kind bootstrap. Delete only the named lab cluster with
`scripts/destroy-kind.ps1` or `scripts/destroy-kind.sh`.
