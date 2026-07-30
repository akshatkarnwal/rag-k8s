import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.rag import build_rag_chain
from app.ingest import ingest_documents
from app.metrics import QUERY_COUNT, QUERY_LATENCY, CHUNKS_RETRIEVED
from app.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up — ingesting documents...")
    ingest_documents()
    app.state.rag_chain, app.state.retriever = build_rag_chain()
    print("RAG chain ready")
    yield
    print("Shutting down")

app = FastAPI(
    title="RAG on K8s",
    description="Production RAG pipeline — FastAPI + pgvector + Gemini",
    version="1.0.0",
    lifespan=lifespan
)

class QueryRequest(BaseModel):
    question: str

class QueryResponse(BaseModel):
    question: str
    answer: str
    latency_ms: float
    chunks_retrieved: int

@app.get("/")
def root():
    return {"status": "running", "model": settings.llm_model}

@app.get("/health")
def health():
    return {"status": "ok", "collection": settings.collection_name}

@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest, req: Request):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    start = time.time()
    try:
        retrieved_docs = req.app.state.retriever.invoke(request.question)
        answer = req.app.state.rag_chain.invoke(request.question)
        latency = time.time() - start

        QUERY_COUNT.labels(status="success").inc()
        QUERY_LATENCY.observe(latency)
        CHUNKS_RETRIEVED.observe(len(retrieved_docs))

        return QueryResponse(
            question=request.question,
            answer=answer,
            latency_ms=round(latency * 1000, 2),
            chunks_retrieved=len(retrieved_docs)
        )
    except Exception as e:
        QUERY_COUNT.labels(status="error").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)