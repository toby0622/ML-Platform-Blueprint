[CmdletBinding()]
param(
    [string]$ClusterName = "ml-platform",
    [switch]$WithKfp
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

$versions = @{}
Get-Content -LiteralPath (Join-Path $RepositoryRoot "infra/cluster/versions.env") |
    Where-Object { $_ -and -not $_.StartsWith("#") } |
    ForEach-Object {
        $key, $value = $_ -split "=", 2
        $versions[$key] = $value
    }

foreach ($tool in @("kind", "kubectl", "helm")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Missing required tool: $tool"
    }
}

$clusters = @(kind get clusters)
if ($clusters -notcontains $ClusterName) {
    kind create cluster `
        --name $ClusterName `
        --image $versions.KIND_NODE_IMAGE `
        --config (Join-Path $RepositoryRoot "infra/cluster/kind-config.yaml") `
        --wait 5m
}

kubectl config use-context "kind-$ClusterName"

helm repo add jetstack https://charts.jetstack.io
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo add argo https://argoproj.github.io/argo-helm
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

$certManagerVersion = $versions.CERT_MANAGER_VERSION.TrimStart("v")
helm upgrade --install cert-manager jetstack/cert-manager `
    --namespace cert-manager `
    --create-namespace `
    --version $certManagerVersion `
    --set crds.enabled=true `
    --wait --timeout 5m

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack `
    --namespace monitoring `
    --create-namespace `
    --version $versions.PROMETHEUS_STACK_CHART_VERSION `
    --set grafana.enabled=true `
    --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false `
    --wait --timeout 10m

helm upgrade --install kueue oci://registry.k8s.io/kueue/charts/kueue `
    --namespace kueue-system `
    --create-namespace `
    --version $versions.KUEUE_VERSION `
    --wait --timeout 5m

$kserveBase = "https://github.com/kserve/kserve/releases/download/$($versions.KSERVE_VERSION)"
kubectl apply --server-side -f "$kserveBase/kserve-crds.yaml"
kubectl apply --server-side -f "$kserveBase/kserve.yaml"
kubectl apply --server-side -f "$kserveBase/kserve-cluster-resources.yaml"
kubectl -n kserve rollout status deployment/kserve-controller-manager --timeout=5m
kubectl -n kserve patch configmap inferenceservice-config --type merge `
    -p '{"data":{"deploy":"{\"defaultDeploymentMode\":\"Standard\"}"}}'

helm upgrade --install kyverno kyverno/kyverno `
    --namespace kyverno `
    --create-namespace `
    --version $versions.KYVERNO_CHART_VERSION `
    --set admissionController.replicas=1 `
    --set backgroundController.replicas=1 `
    --wait --timeout 5m

helm upgrade --install argocd argo/argo-cd `
    --namespace argocd `
    --create-namespace `
    --version $versions.ARGO_CD_CHART_VERSION `
    --wait --timeout 10m

if ($WithKfp) {
    $kfpSource = "github.com/kubeflow/pipelines/manifests/kustomize/env/platform-agnostic?ref=$($versions.KFP_VERSION)"
    kubectl apply --server-side -k $kfpSource
}

kubectl apply -k (Join-Path $RepositoryRoot "platform/argocd")
kubectl apply -k (Join-Path $RepositoryRoot "platform/tenants")
kubectl apply -k (Join-Path $RepositoryRoot "platform/kueue")
kubectl apply -k (Join-Path $RepositoryRoot "platform/policies")

Write-Output "ML platform prerequisites and first-party resources are ready."
Write-Output "Argo CD: kubectl -n argocd port-forward svc/argocd-server 8443:443"
