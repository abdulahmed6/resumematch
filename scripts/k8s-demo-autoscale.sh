#!/usr/bin/env bash
# Show both autoscalers working on the kind cluster from k8s-kind-up.sh:
#  1. KEDA scales the Celery worker Deployment on Redis queue depth.
#  2. The HPA scales the gateway on CPU.
# Leaves a log in k8s-autoscale-demo.log you can point to in an interview.
set -euo pipefail
NS=resumematch
LOG=k8s-autoscale-demo.log
: > "$LOG"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

kubectl -n $NS port-forward svc/scraper-api 18002:8002 >/dev/null 2>&1 &
PF1=$!
kubectl -n $NS port-forward svc/gateway 18000:8000 >/dev/null 2>&1 &
PF2=$!
trap 'kill $PF1 $PF2 2>/dev/null || true' EXIT
sleep 3

log "workers before: $(kubectl -n $NS get deploy worker -o jsonpath='{.status.replicas}')"
log "queueing 150 scrape tasks (52,500 postings)"
for _ in $(seq 150); do
  curl -fsS -X POST localhost:18002/scrape -H 'content-type: application/json' \
    -d '{"source":"synthetic","count":350}' >/dev/null
done
for _ in $(seq 24); do
  depth=$(kubectl -n $NS exec deploy/redis -- redis-cli llen celery | tr -d '\r')
  log "queue depth=$depth  worker replicas=$(kubectl -n $NS get deploy worker -o jsonpath='{.status.replicas}')"
  [ "$depth" = "0" ] && break
  sleep 5
done

log "gateway HPA before: $(kubectl -n $NS get hpa gateway -o jsonpath='{.status.currentReplicas}') replicas"
log "sending search load for 90s"
end=$((SECONDS + 90))
while [ $SECONDS -lt $end ]; do
  for _ in $(seq 20); do
    curl -fsS -X POST localhost:18000/api/search -H 'content-type: application/json' \
      -d '{"query":"senior python backend engineer kubernetes","top_k":10}' >/dev/null &
  done
  wait
done
for _ in $(seq 6); do
  log "gateway: $(kubectl -n $NS get hpa gateway --no-headers)"
  sleep 10
done
log "done; full log in $LOG"
