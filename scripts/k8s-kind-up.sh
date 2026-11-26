#!/usr/bin/env bash
# Deploy the full ResumeMatch stack to a local kind cluster:
#   3 FastAPI services (gateway, embedding, scraper-api), Celery workers +
#   beat, Postgres, Redis, metrics-server (for the gateway HPA), KEDA (for
#   the worker ScaledObject), Prometheus and Grafana.
#
# Requires: docker (running), kind, kubectl.  Takes ~5-10 minutes the first
# time (image build + pulls).  Re-running is safe.
set -euo pipefail

CLUSTER=resumematch
NS=resumematch
IMAGE=resumematch-backend:dev
KEDA_VERSION=2.16.1
METRICS_SERVER_VERSION=v0.7.2
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

step() { printf '\n==> %s\n' "$*"; }
need() { command -v "$1" >/dev/null || { echo "missing: $1 ($2)"; exit 1; }; }
need docker "https://docs.docker.com/get-docker/"
need kind "brew install kind  |  https://kind.sigs.k8s.io/docs/user/quick-start/"
need kubectl "brew install kubectl  |  https://kubernetes.io/docs/tasks/tools/"

step "Creating kind cluster '$CLUSTER'"
if kind get clusters | grep -qx "$CLUSTER"; then
  echo "already exists"
else
  kind create cluster --config "$ROOT/k8s/overlays/kind/cluster.yaml" --wait 120s
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null

step "Building $IMAGE and loading it into the cluster (no registry needed)"
docker build -f "$ROOT/docker/backend.Dockerfile" -t "$IMAGE" "$ROOT"
kind load docker-image "$IMAGE" --name "$CLUSTER"

step "Installing metrics-server $METRICS_SERVER_VERSION (CPU metrics for the gateway HPA)"
kubectl apply -f "https://github.com/kubernetes-sigs/metrics-server/releases/download/${METRICS_SERVER_VERSION}/components.yaml"
# kind's kubelets use self-signed certs.
kubectl -n kube-system patch deployment metrics-server --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' 2>/dev/null || true

step "Installing KEDA $KEDA_VERSION (queue-depth autoscaling for the workers)"
kubectl apply --server-side -f "https://github.com/kedacore/keda/releases/download/v${KEDA_VERSION}/keda-${KEDA_VERSION}.yaml"
kubectl -n keda rollout status deployment/keda-operator --timeout=180s
kubectl -n keda rollout status deployment/keda-operator-metrics-apiserver --timeout=180s

step "Applying ResumeMatch (k8s/overlays/kind)"
kubectl apply -k "$ROOT/k8s/overlays/kind"

step "Waiting for rollouts"
for d in postgres redis embedding gateway scraper-api worker beat prometheus grafana; do
  kubectl -n "$NS" rollout status "deployment/$d" --timeout=300s
done

step "Seeding 20 x 350 synthetic postings through the worker pool"
kubectl -n "$NS" port-forward svc/scraper-api 18002:8002 >/dev/null 2>&1 &
PF=$!; trap 'kill $PF 2>/dev/null || true' EXIT; sleep 3
for _ in $(seq 20); do
  curl -fsS -X POST localhost:18002/scrape -H 'content-type: application/json' \
    -d '{"source":"synthetic","count":350}' >/dev/null
done
echo "queued"

step "Done"
kubectl -n "$NS" get pods,hpa,scaledobject
cat <<MSG

Open the services (one terminal each):
  kubectl -n $NS port-forward svc/gateway 8000:8000      # app + API docs at http://localhost:8000
  kubectl -n $NS port-forward svc/grafana 3001:3000      # dashboards at http://localhost:3001
  kubectl -n $NS port-forward svc/prometheus 9090:9090   # targets at http://localhost:9090/targets

Watch autoscaling:   scripts/k8s-demo-autoscale.sh
Tear down:           kind delete cluster --name $CLUSTER
MSG
