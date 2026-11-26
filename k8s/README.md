# ResumeMatch on Kubernetes

These manifests translate `docker-compose.yml` into a Kubernetes deployment,
adding a CPU-based HPA on the gateway and a KEDA queue-depth ScaledObject on
the worker pool.

## Layout

| Path | What it is |
|---|---|
| `base/` | The app: 3 FastAPI services, Celery workers + beat, Postgres, Redis, gateway HPA, worker KEDA ScaledObject |
| `monitoring/` | Prometheus (pod service discovery) and Grafana with the provisioned ResumeMatch dashboard |
| `overlays/kind/` | Local cluster: base + monitoring, a locally built image, and a generated Secret for the in-cluster datastores |

## Quick start on kind (local)

```bash
scripts/k8s-kind-up.sh          # cluster, image, metrics-server, KEDA, app, monitoring, seed data
scripts/k8s-demo-autoscale.sh   # queue 150 tasks -> KEDA adds workers; search load -> HPA adds gateways
```

Needs Docker, `kind` and `kubectl`. The first run takes about 5–10 minutes.
The demo writes `k8s-autoscale-demo.log` with queue depth and replica counts
over time, so you can show autoscaling actually happened.

The manifests render and pass `kubeconform -strict` against Kubernetes
1.32 schemas. The KEDA ScaledObject is a CRD, so it is skipped by that check.
I couldn't run `k8s-kind-up.sh` end to end in the environment these were
written in (containers inside its Docker couldn't start). Run it once on your
own machine and keep `k8s-autoscale-demo.log` as the evidence.

## Prerequisites

1. **A container image.** There's no CI step in this repo yet that builds
   and pushes one (docker-compose.yml builds `docker/backend.Dockerfile`
   locally). Build and push your own, then update the `image:` field in
   every `deployment-*.yaml` (or override centrally via kustomize's
   `images:` transformer in `kustomization.yaml`):
   ```
   docker build -f docker/backend.Dockerfile -t ghcr.io/<you>/resumematch-backend:latest .
   docker push ghcr.io/<you>/resumematch-backend:latest
   ```
2. **metrics-server**, for `hpa-gateway.yaml` (CPU-based autoscaling). Most
   managed clusters have this by default; kind/minikube need it enabled
   explicitly (`minikube addons enable metrics-server`, or apply
   `components.yaml` from the metrics-server repo on kind).
3. **KEDA**, for `scaledobject-worker.yaml` (queue-depth-based autoscaling
   of the Celery worker pool):
   ```
   helm repo add kedacore https://kedacore.github.io/charts
   helm install keda kedacore/keda --namespace keda --create-namespace
   ```
   Without KEDA installed, `deployment-worker.yaml`'s `replicas: 3` still
   applies as a static baseline -- you just lose the autoscaling on top.

## Real datastores vs. in-cluster convenience

`postgres.yaml` and `redis.yaml` run single-replica, no-backup, no-auth
Postgres/Redis *inside* the cluster. They exist so you can try the rest of
these manifests on kind/minikube without standing up managed services
first. They are explicitly **not** a production-ready substitute for a
managed, backed-up datastore (RDS/Cloud SQL for Postgres; ElastiCache /
Upstash / Memorystore for Redis) -- see the comments at the top of each
file. For a real deployment, point `secret.yaml`'s `RM_DATABASE_URL` /
`RM_REDIS_URL` at your managed instances and don't apply `postgres.yaml` /
`redis.yaml` at all.

## Setup on a real cluster

```bash
cp k8s/base/secret.example.yaml k8s/base/secret.yaml
# edit secret.yaml: fill in RM_DATABASE_URL / RM_REDIS_URL for real
kubectl apply -f k8s/base/namespace.yaml -f k8s/base/secret.yaml
kubectl apply -k k8s/base          # add: kubectl apply -k k8s/monitoring
```

## What scales, and on what

| Component | Replicas | Scaling |
|---|---|---|
| `gateway` | 2 (baseline) | `hpa-gateway.yaml`: CPU-based, autoscaling/v2, min 2 / max 6, target 70% average CPU utilization |
| `scraper-api` | 2 (fixed) | none configured -- add an HPA the same way as gateway's if needed |
| `worker` | 3 (baseline) | `scaledobject-worker.yaml`: KEDA `redis` scaler, watches the length of the `celery` broker list (the default Celery queue name -- see `backend/scraper/celery_app.py`, no `task_default_queue` override), min 3 / max 10 |
| `embedding` | 1 (pinned) | **not scaled** -- see `deployment-embedding.yaml`'s header: it owns a local FAISS index file on a PVC with no locking or replication between processes, so more than one replica would each see a different index |
| `beat` | 1 (pinned) | **must never be scaled** -- more than one beat process double-enqueues the periodic scrape schedule |
| `postgres`, `redis` | 1 each | dev/test convenience only, see above |

## Known gaps / not done here

- The worker pods don't expose `/metrics`, so the dashboard's scrape-task
  panels stay empty in Kubernetes (and in docker-compose). Request rate,
  latency and DLQ depth from the three services do show.
- No Ingress / TLS termination -- `service-gateway.yaml` is a plain
  ClusterIP; put an Ingress or LoadBalancer Service in front of it for
  external access.
- No NetworkPolicies, PodDisruptionBudgets, or resource quotas at the
  namespace level.
- No `TriggerAuthentication` for the KEDA Redis trigger -- add one if you
  point `RM_REDIS_URL` at a password-protected Redis (neither
  docker-compose's Redis nor `redis.yaml`'s in-cluster Redis sets
  `requirepass` today).
- No CI pipeline that builds/pushes the image referenced in these
  manifests -- see Prerequisites above.
