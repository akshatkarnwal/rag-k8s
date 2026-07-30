from pathlib import Path
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import PGVector
from app.config import settings
from app.rag import get_embeddings
from app.metrics import DOCS_INDEXED

def ingest_documents(data_dir: str = "data") -> int:
    data_path = Path(data_dir)
    if not data_path.exists() or not any(data_path.iterdir()):
        print(f"No documents found in {data_dir}/, using sample data")
        return ingest_sample_data()

    print(f"Loading documents from {data_dir}/")
    loader = DirectoryLoader(
        data_dir,
        glob="**/*.txt",
        loader_cls = TextLoader
    )
    raw_docs = loader.load()
    print(f"Loader {len(raw_docs)} documents")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size = settings.chunk_size,
        chunk_overlap = settings.chunk_overlap
    )
    chunks = splitter.split_documents(raw_docs)
    print(f"Split into {len(chunks)} chunks")

    PGVector.from_documents(
        documents = chunks,
        embedding = get_embeddings(),
        collection_name = settings.collection_name,
        connection_string=settings.connection_string,
        pre_delete_collection = True
    )

    DOCS_INDEXED.set(len(chunks))
    print(f"Ingested {len(chunks)} chunks into pgvector")
    return len(chunks)
    
def ingest_sample_data() -> int:
    from langchain_core.documents import Document
    docs = [
        Document(page_content="To restart the DNIF worker: systemctl restart dnif-worker", metadata={"source": "cpu_runbook"}),
        Document(page_content="High CPU alert fires when usage exceeds 85% for 5 minutes. Severity P2.", metadata={"source": "cpu_runbook"}),
        Document(page_content="Check worker logs: journalctl -u dnif-worker -n 100", metadata={"source": "cpu_runbook"}),
        Document(page_content="Regex backtracking in extraction rules causes high CPU. Optimise patterns.", metadata={"source": "cpu_runbook"}),
        Document(page_content="Pause data source from DNIF console to reduce ingestion load.", metadata={"source": "cpu_runbook"}),
        Document(page_content="Escalate to platform-team@company.com if CPU stays high after restart.", metadata={"source": "cpu_runbook"}),
    ]
    PGVector.from_documents(
        documents=docs,
        embedding=get_embeddings(),
        collection_name=settings.collection_name,
        connection_string=settings.connection_string,
        pre_delete_collection=True
    )
    DOCS_INDEXED.set(len(docs))
    print(f"Ingested {len(docs)} sample chunks")
    return len(docs)