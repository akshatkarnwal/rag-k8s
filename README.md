# RAG on Kubernetes

[![CI](https://github.com/akshatkarnwal/rag-k8s/actions/workflows/ci.yml/badge.svg)](https://github.com/akshatkarnwal/rag-k8s/actions/workflows/ci.yml)

Production RAG pipeline deployed on Kubernetes — FastAPI + pgvector + Gemini + Prometheus + Grafana.

## Architecture

```mermaid
flowchart LR
    A[User Query] --> B[FastAPI]
    B --> C[LangChain]
    C --> D["pgvector<br/>Semantic Search"]
    D --> E[Gemini]
    E --> F[Response]

    B --> G["/metrics"]
    G --> H[Prometheus]
    H --> I[Grafana Dashboard]
```

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
| Auth             | JWT (python-jose/bcrypt)      |
| Testing & CI     | pytest, pytest-mock, GitHub Actions |

## Features

- Document ingestion pipeline with chunking and embedding
- Semantic search over pgvector with cosine similarity
- Production FastAPI with liveness and readiness probes
- JWT-authenticated `/query` endpoint — `/health` and `/metrics` remain open for probes/scraping
- Prometheus metrics: query rate, P95 latency, docs indexed, chunks retrieved
- Grafana dashboards for real-time observability
- HPA autoscaling between 1-3 replicas
- Kubernetes Secrets for API key management
- Automated test suite (pytest) with mocked dependencies, run on every push and pull request via GitHub Actions

## Quick Start

### Local development

```bash
# clone and setup
git clone https://github.com/akshatkarnwal/rag-k8s
cd rag-k8s
cp .env.example .env  # add your GEMINI_API_KEY and auth settings — see Authentication section below

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

## Authentication

The `/query` endpoint requires a JWT bearer token. `/health` and `/metrics`
are intentionally left open, since health probes and Prometheus scraping
shouldn't require a login.

```bash
# 1. get a token
curl -X POST http://localhost:8000/token \
  -d "username=<your-username>&password=<your-password>"

# 2. use it to call the protected endpoint
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <paste-token-here>" \
  -d '{"question": "How do I restart the DNIF worker?"}'
```

This project uses a single demo user (configured via environment
variables) rather than a full user table — a reasonable, honest scope
for a personal project. Swapping `verify_demo_user()` in `app/auth.py`
for a real lookup against a `users` table in the existing Postgres
instance would be the natural next step for a multi-user system; the
JWT issuance/verification mechanics stay the same either way.

Required environment variables (see `.env.example`):

|      Variable        |                  Purpose                    |
|-----------------------|----------------------------------------------|
| `JWT_SECRET_KEY`      | Signing key for tokens — generate with `openssl rand -hex 32` |
| `JWT_EXPIRE_MINUTES`  | Token lifetime (default: 60)                  |
| `DEMO_USERNAME`       | The single demo user's username               |
| `DEMO_PASSWORD_HASH`  | Bcrypt hash of the demo password — never store plaintext |

## API

```bash
# health check (no auth required)
curl http://localhost:8000/health

# query (auth required — see Authentication section)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"question": "How do I restart the DNIF worker?"}'

# prometheus metrics (no auth required)
curl http://localhost:8000/metrics
```

## Testing

The test suite mocks `ingest_documents` and `build_rag_chain` before FastAPI's
lifespan runs, so tests never touch a real Postgres instance or the real
Gemini API — fast, free, and deterministic. Auth-related tests patch
`app/auth.py`'s module-level constants directly (rather than just the
environment), since those values are read once at import time.

```bash
# install test dependencies
uv add --dev pytest pytest-mock httpx

# run the suite
uv run pytest -v
```

Coverage includes:
- Root and health endpoint checks
- Prometheus metrics endpoint (format and increment-on-request)
- Auth: successful login, wrong username/password, missing/invalid token
- `/query` happy path (with a valid token), with exact response-shape assertions
- Validation: missing `question` field (422) vs. empty/whitespace string (400)
- Error handling: retriever failure correctly surfaces as a 500

## CI/CD

Every push and pull request to `master` runs the full test suite via GitHub
Actions (`.github/workflows/ci.yml`), using `uv sync --locked` to install
the exact dependency versions from `uv.lock` — so CI always matches what's
tested locally, not just whatever resolves at the time. The workflow
supplies dummy auth credentials as environment variables (never real
secrets) so the test suite's auth coverage runs the same way in CI as
it does locally.

## Key Design Decisions

**Why pgvector over Pinecone?**
pgvector runs inside PostgreSQL — no additional infrastructure. For thousands to millions of documents, it's the right tradeoff between simplicity and scale.

**Why chunk_size=500, overlap=100?**
Small chunks lose context; large chunks reduce retrieval precision. 500 characters with 100-character overlap preserves semantic units while keeping retrieval focused.

**Why HPA on CPU+memory?**
LLM inference is CPU-bound for embedding generation. Memory-based scaling catches pgvector connection pool exhaustion before it causes errors.

**Why Kubernetes Secrets for API keys?**
Secrets are injected as environment variables at runtime — rotating a key means updating the Secret and rolling the Deployment, with no code change required.

**Why mock the RAG chain in tests instead of hitting the real Gemini API?**
Gemini's free tier is tightly rate-limited. Mocking `build_rag_chain` and
`ingest_documents` at the FastAPI lifespan boundary keeps the test suite
fast and free to run on every single commit, while still exercising the
real request/response contract of the API itself.

**Why a single demo user instead of a full auth system?**
Scope-appropriate for a personal project — the goal was to demonstrate
real JWT issuance/verification mechanics on a production-shaped API, not
to build a user-management system. The mechanics (signing, expiry,
bearer-token verification) are identical to what a multi-user system
would use.

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
- Testing FastAPI apps with lifespan-managed state: mocking dependencies
  before `TestClient` triggers startup, rather than patching after the fact
- Wiring GitHub Actions CI end-to-end, including debugging real issues
  along the way (pytest import path via `pythonpath` in `pyproject.toml`,
  matching the Python version to the local environment, and matching the
  workflow's branch trigger to the repo's actual default branch)
- Implementing JWT auth with FastAPI's `OAuth2PasswordBearer` /
  `Depends()` pattern, and the importance of when environment variables
  get read: module-level reads at import time need to be patched at the
  attribute level in tests, not just via the environment, since the
  module only reads `os.environ` once
- Debugging a CI-only test failure caused by `.env` existing locally but
  not on the CI runner (correctly, since it's gitignored) — fixed by
  supplying dummy test credentials directly in the workflow's `env:` block
