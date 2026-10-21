import logging
import time
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import create_engine, text

from app.rag import build_rag_chain
from app.ingest import ingest_documents
from app.metrics import QUERY_COUNT, QUERY_LATENCY, CHUNKS_RETRIEVED
from app.config import settings
from app.auth import verify_demo_user, create_access_token, get_current_user

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag-k8s")


@lru_cache(maxsize=1)
def get_engine():
    # Lazy so importing this module (e.g. in tests) never opens a connection.
    return create_engine(settings.connection_string, pool_pre_ping=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ingest_on_startup:
        logger.info("INGEST_ON_STARTUP is set - ingesting documents")
        ingest_documents()
    else:
        logger.info("Skipping ingestion at startup (use `python -m app.ingest` or the ingest Job)")
    app.state.rag_chain = build_rag_chain()
    logger.info("RAG chain ready")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="RAG on K8s",
    description="Production RAG pipeline — FastAPI + pgvector + Gemini",
    version="1.0.0",
    lifespan=lifespan,
)


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    question: str
    answer: str
    latency_ms: float
    chunks_retrieved: int


def _is_quota_error(exc: Exception) -> bool:
    # String match is crude; once you know the exception class your
    # langchain-google-genai version raises on a 429, catch that class instead.
    msg = str(exc)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg


@app.get("/")
def root():
    return {"status": "running", "model": settings.llm_model}


@app.get("/health")
def health():
    # Liveness: cheap, no dependencies.
    return {"status": "ok", "collection": settings.collection_name}


@app.get("/ready")
def ready(req: Request):
    # Readiness: chain is built and Postgres is reachable.
    if getattr(req.app.state, "rag_chain", None) is None:
        raise HTTPException(status_code=503, detail="RAG chain not initialised")
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Readiness check failed: database unreachable")
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ready"}


@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if not verify_demo_user(form_data.username, form_data.password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = create_access_token(form_data.username)
    return {"access_token": token, "token_type": "bearer"}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest, req: Request, current_user: str = Depends(get_current_user)):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    start = time.perf_counter()
    try:
        # One retrieval per request: the chain returns docs and answer together.
        result = req.app.state.rag_chain.invoke(request.question)
        answer = result["answer"]
        n_chunks = len(result["docs"])
    except Exception as e:
        # Record latency for failures too, so slow failures show up in P95.
        QUERY_LATENCY.observe(time.perf_counter() - start)
        QUERY_COUNT.labels(status="error").inc()
        if _is_quota_error(e):
            logger.warning("Gemini quota / rate limit hit: %s", e)
            raise HTTPException(
                status_code=503,
                detail="Model quota exhausted, please retry later",
                headers={"Retry-After": "60"},
            )
        logger.exception("Query failed")
        raise HTTPException(status_code=500, detail="Internal server error")

    latency = time.perf_counter() - start
    QUERY_COUNT.labels(status="success").inc()
    QUERY_LATENCY.observe(latency)
    CHUNKS_RETRIEVED.observe(n_chunks)

    return QueryResponse(
        question=request.question,
        answer=answer,
        latency_ms=round(latency * 1000, 2),
        chunks_retrieved=n_chunks,
    )


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)