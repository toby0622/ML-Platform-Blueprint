#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/infra/cluster/versions.env"

CLUSTER_NAME="${CLUSTER_NAME:-ml-platform}"
WITH_KFP="${WITH_KFP:-false}"

for tool in kind kubectl helm; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "missing required tool: ${tool}" >&2
    exit 1
  fi
done

if ! kind get clusters | grep -Fxq "${CLUSTER_NAME}"; then
  kind create cluster \
    --name "${CLUSTER_NAME}" \
    --image "${KIND_NODE_IMAGE}" \
    --config "${ROOT_DIR}/infra/cluster/kind-config.yaml" \
    --wait 5m
fi

kubectl config use-context "kind-${CLUSTER_NAME}"

helm repo add jetstack https://charts.jetstack.io
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo add argo https://argoproj.github.io/argo-helm
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version "${CERT_MANAGER_VERSION#v}" \
  --set crds.enabled=true \
  --wait --timeout 5m

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --version "${PROMETHEUS_STACK_CHART_VERSION}" \
  --set grafana.enabled=true \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --wait --timeout 10m

helm upgrade --install kueue oci://registry.k8s.io/kueue/charts/kueue \
  --namespace kueue-system \
  --create-namespace \
  --version "${KUEUE_VERSION}" \
  --wait --timeout 5m

kubectl apply --server-side \
  -f "https://github.com/kserve/kserve/releases/download/${KSERVE_VERSION}/kserve-crds.yaml"
kubectl apply --server-side \
  -f "https://github.com/kserve/kserve/releases/download/${KSERVE_VERSION}/kserve.yaml"
kubectl apply --server-side \
  -f "https://github.com/kserve/kserve/releases/download/${KSERVE_VERSION}/kserve-cluster-resources.yaml"
kubectl -n kserve rollout status deployment/kserve-controller-manager --timeout=5m
kubectl -n kserve patch configmap inferenceservice-config --type merge \
  -p '{"data":{"deploy":"{\"defaultDeploymentMode\":\"Standard\"}"}}'

helm upgrade --install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  --version "${KYVERNO_CHART_VERSION}" \
  --set admissionController.replicas=1 \
  --set backgroundController.replicas=1 \
  --wait --timeout 5m

helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --version "${ARGO_CD_CHART_VERSION}" \
  --wait --timeout 10m

if [[ "${WITH_KFP}" == "true" ]]; then
  kubectl apply --server-side -k \
    "github.com/kubeflow/pipelines/manifests/kustomize/env/platform-agnostic?ref=${KFP_VERSION}"
fi

kubectl apply -k "${ROOT_DIR}/platform/argocd"
kubectl apply -k "${ROOT_DIR}/platform/tenants"
kubectl apply -k "${ROOT_DIR}/platform/kueue"
kubectl apply -k "${ROOT_DIR}/platform/policies"

echo "ML platform prerequisites and first-party resources are ready."
echo "Argo CD: kubectl -n argocd port-forward svc/argocd-server 8443:443"
