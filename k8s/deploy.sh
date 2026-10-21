#!/usr/bin/env bash
# Build the API image, tag it with the git short SHA, and roll it out to minikube.
#   ./deploy.sh            deploy the app
#   ./deploy.sh --ingest   also (re)run the one-off ingestion Job first
# Prerequisite: k8s/secret.yaml has been applied once (it is gitignored).
set -euo pipefail

TAG=$(git rev-parse --short HEAD)
if [[ -n "$(git status --porcelain)" ]]; then
  echo "warning: uncommitted changes; image tag $TAG will not match the running code exactly" >&2
fi

if ! kubectl get secret rag-k8s-secret >/dev/null 2>&1; then
  echo "error: secret rag-k8s-secret not found. Run: kubectl apply -f k8s/secret.yaml" >&2
  exit 1
fi

# Build inside minikube's Docker daemon so imagePullPolicy: Never finds the image.
eval "$(minikube docker-env)"
docker compose build rag-api
docker tag rag-k8s-rag-api:latest "rag-k8s-rag-api:${TAG}"

kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/pgvector-deployment.yaml -f k8s/pgvector-service.yaml
kubectl rollout status deployment/pgvector --timeout=180s

if [[ "${1:-}" == "--ingest" ]]; then
  # Job specs are immutable, so remove the previous run first.
  # Note: the job replaces the whole collection, so queries can briefly return nothing.
  kubectl delete job rag-k8s-ingest --ignore-not-found
  sed "s/IMAGE_TAG/${TAG}/g" k8s/ingest-job.yaml | kubectl apply -f -
  kubectl wait --for=condition=complete job/rag-k8s-ingest --timeout=300s
fi

sed "s/IMAGE_TAG/${TAG}/g" k8s/deployment.yaml | kubectl apply -f -
kubectl apply -f k8s/service.yaml -f k8s/hpa.yaml
kubectl apply -f k8s/servicemonitor.yaml \
  || echo "warning: ServiceMonitor not applied (Prometheus Operator CRDs missing?)" >&2

kubectl rollout status deployment/rag-k8s --timeout=300s
echo "Deployed rag-k8s-rag-api:${TAG}"
kubectl get deployment rag-k8s -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
