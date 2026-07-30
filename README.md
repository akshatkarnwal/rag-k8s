# RAG on Kubernetes

Production RAG pipeline deployed on Kubernetes — FastAPI + pgvector + Gemini + Prometheus + Grafana.

## Architecture
User Query → FastAPI → LangChain → pgvector (semantic search) → Gemini → Response
↓
Prometheus /metrics
↓
Grafana Dashboard

## Stack

|     Component    |           Technology          |
|------------------|-------------------------------|
| API              | FastAPI + Uvicorn             |
| RAG Framework    | LangChain                     |
| Vector DB        | pgvector (PostgreSQL)         |
| LLM              | Gemini 2.5 Flash              |
| Embeddings       | Gemini Embedding 2 (3072-dim) |
| Orchestration    | Kubernetes (minikube)         |
| Autoscaling      | HPA (CPU + memory based)      |
| Observability    | Prometheus + Grafana          |
| Containerisation | Docker                        |

## Features

- Document ingestion pipeline with chunking and embedding
- Semantic search over pgvector with cosine similarity
- Production FastAPI with liveness and readiness probes
- Prometheus metrics: query rate, P95 latency, docs indexed, chunks retrieved
- Grafana dashboards for real-time observability
- HPA autoscaling between 1-3 replicas
- Kubernetes Secrets for API key management

## Quick Start

### Local development

```bash
# clone and setup
git clone https://github.com/akshatkarnwal/rag-k8s
cd rag-k8s
cp .env.example .env  # add your GEMINI_API_KEY

# start pgvector
docker run -d --name pgvector \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=vectordb \
  -p 5432:5432 pgvector/pgvector:pg16

# install and run
uv init && uv add -r requirements.txt
uv run uvicorn app.main:app --reload --port 8000
```

### Deploy to Kubernetes

```bash
# start minikube
minikube start
minikube image load rag-k8s:latest

# deploy
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml      # add your keys first
kubectl apply -f k8s/pgvector-deployment.yaml
kubectl apply -f k8s/pgvector-service.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/hpa.yaml

# get service URL
minikube service rag-k8s-service --url
```

## API

```bash
# health check
curl http://localhost:8000/health

# query
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I restart the DNIF worker?"}'

# prometheus metrics
curl http://localhost:8000/metrics
```

## Key Design Decisions

**Why pgvector over Pinecone?**
pgvector runs inside PostgreSQL — no additional infrastructure. For thousands to millions of documents, it's the right tradeoff between simplicity and scale.

**Why chunk_size=500, overlap=100?**
Small chunks lose context; large chunks reduce retrieval precision. 500 characters with 100-character overlap preserves semantic units while keeping retrieval focused.

**Why HPA on CPU+memory?**
LLM inference is CPU-bound for embedding generation. Memory-based scaling catches pgvector connection pool exhaustion before it causes errors.

**Why Kubernetes Secrets for API keys?**
Secrets are injected as environment variables at runtime — rotating a key means updating the Secret and rolling the Deployment, with no code change required.

## Observability

Prometheus scrapes `/metrics` every 15 seconds via ServiceMonitor.

|           Metric            |    Type   |        Description            |
|-----------------------------|-----------|-------------------------------|
| `rag_query_total`           | Counter   | Total queries by status       |
| `rag_query_latency_seconds` | Histogram | Query latency (P50/P95/P99)   |
| `rag_chunks_retrieved`      | Histogram | Chunks retrieved per query    |
| `rag_docs_indexed_total`    | Gauge     | Documents indexed in pgvector |

## What I Learned

- End-to-end RAG pipeline architecture
- pgvector HNSW index for approximate nearest neighbour search
- Kubernetes Deployments, Services, ConfigMaps, Secrets, HPA
- Prometheus ServiceMonitor for automatic target discovery
- Production FastAPI patterns: lifespan, health probes, metrics endpoint