from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import PGVector
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from app.config import settings

RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an AI assistant for platform engineers.
Answer questions using ONLY the context provided below.
If the answer is not in the context, say: "That information is not in the documentation."
Be concise and practical.

Context:
{context}"""),
    ("human", "{question}")
])

def get_llm():
    return ChatGoogleGenerativeAI(
        model = settings.llm_model,
        google_api_key = settings.gemini_api_key
    )

def get_embeddings():
    return GoogleGenerativeAIEmbeddings(
        model = settings.embedding_model,
        google_api_key = settings.gemini_api_key
    )

def get_vectorstore():
    return PGVector(
        embedding_function = get_embeddings(),
        collection_name = settings.collection_name,
        connection_string = settings.connection_string
    )

def get_retriever():
    return get_vectorstore().as_retriever(
        search_kwargs={"k": settings.retrievel_k}
    )

def format_docs(docs):
    return "\n\n---\n\n".join(
        f"[source: {doc.metadata.get('source','unknown')}]\n{doc.page_content}"
        for doc in docs
    )

def build_rag_chain():
    retriever = get_retriever()
    llm = get_llm()
    chain = (
        {
            "context" : retriever | format_docs,
            "question" : RunnablePassthrough()
        }
        | RAG_PROMPT
        | llm
        | StrOutputParser()
    )
    return chain, retriever