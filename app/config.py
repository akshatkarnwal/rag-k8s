import os
from dataclasses import dataclass


@dataclass
class Settings:

    # API
    gemini_api_key : str = os.environ.get("GEMINI_API_KEY","")

    # Models
    llm_model : str = "gemini-2.5-flash"
    embedding_model : str = "models/gemini-embedding-2"

    # pgvector
    db_host : str = os.environ.get("DB_HOST","localhost")
    db_port : str = os.environ.get("DB_PORT","5432")
    db_name : str = os.environ.get("DB_NAME","vectordb")
    db_user : str = os.environ.get("DB_USER","postgres")
    db_password : str = os.environ.get("DB_PASSWORD","postgres")
    collection_name : str = "rag_k8s_docs"

    # RAG
    chunk_size : int = 500
    chunk_overlap : int = 100
    retrievel_k : int = 4

    @property
    def connection_string(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

settings = Settings()