from prometheus_client import Counter, Histogram, Gauge

# track every query
QUERY_COUNT = Counter(
    "rag_query_total",
    "Total number of RAG queries",
    ["status"]
)

# track how long queries take
QUERY_LATENCY = Histogram(
    "rag_query_latency_seconds",
    "RAG query latency in seconds",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

# tracked chunks retrieved per query 
CHUNKS_RETRIEVED = Histogram(
    "rag_chunks_retrieved",
    "Number of chunks retrieved per query",
    buckets=[1, 2, 3, 4, 5, 8, 10]
)

# track how many docs are indexed
DOCS_INDEXED = Gauge(
    "rag_docs_indexed_total",
    "Total number of document chunks indexed in pgvector"
)

