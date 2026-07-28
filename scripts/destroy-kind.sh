#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-ml-platform}"

if ! command -v kind >/dev/null 2>&1; then
  echo "missing required tool: kind" >&2
  exit 1
fi

if kind get clusters | grep -Fxq "${CLUSTER_NAME}"; then
  kind delete cluster --name "${CLUSTER_NAME}"
else
  echo "kind cluster ${CLUSTER_NAME} does not exist; nothing to delete"
fi
