import os
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from utils.logger import get_logger

logger = get_logger("vector_store")

VECTOR_DIR = "vector_db/faiss_index"

_retriever = None


def get_embeddings():
    provider = os.getenv("LLM_PROVIDER", "openai").lower()

    if provider == "gemini":
        return GoogleGenerativeAIEmbeddings(model="models/embedding-001")

    return OpenAIEmbeddings()


def get_retriever():
    global _retriever

    if _retriever:
        return _retriever

    if not os.path.exists(VECTOR_DIR):
        raise RuntimeError(
            "Vector index not found. "
            "Run scripts/build_vector_index.py first."
        )

    logger.info("Loading FAISS vector index from disk")
    embeddings = get_embeddings()
    db = FAISS.load_local(
    VECTOR_DIR,
    embeddings,
    allow_dangerous_deserialization=True
    )


    _retriever = db.as_retriever()
    logger.info("Vector retriever ready")

    return _retriever
