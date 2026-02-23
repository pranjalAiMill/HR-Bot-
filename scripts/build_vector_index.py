from dotenv import load_dotenv
load_dotenv()

import os
from pathlib import Path

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from utils.logger import get_logger

logger = get_logger("vector_builder")

POLICY_DIR = Path("policies")
VECTOR_DIR = "vector_db/faiss_index"


def get_embeddings():
    provider = os.getenv("LLM_PROVIDER", "").lower()

    if provider == "gemini":
        logger.info("Using Gemini embeddings")
        return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

    if provider == "openai":
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set")
        logger.info("Using OpenAI embeddings")
        return OpenAIEmbeddings()

    raise RuntimeError(
        "LLM_PROVIDER must be set to 'gemini' or 'openai'"
    )

def build_index():
    logger.info("Starting vector index build")

    if not POLICY_DIR.exists():
        raise RuntimeError(f"Policy directory not found: {POLICY_DIR}")

    policy_files = list(POLICY_DIR.glob("*.txt"))

    if not policy_files:
        raise RuntimeError("No policy files found in policies/ directory")

    logger.info(f"Found {len(policy_files)} policy files")

    all_chunks = []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=300,
        separators=["\n\n", "\n", "—", ".", " "]
    )

    for policy_path in policy_files:
        logger.info(f"Processing policy file: {policy_path.name}")

        loader = TextLoader(str(policy_path))
        docs = loader.load()

        chunks = splitter.split_documents(docs)

        for i, c in enumerate(chunks):
            c.metadata = {
                "policy": policy_path.stem,
                "section": f"Section {i + 1}"
            }

        all_chunks.extend(chunks)

        logger.info(f"  → Chunks created: {len(chunks)}")

    logger.info(f"Total chunks across all policies: {len(all_chunks)}")

    embeddings = get_embeddings()
    db = FAISS.from_documents(all_chunks, embeddings)

    os.makedirs(VECTOR_DIR, exist_ok=True)
    db.save_local(VECTOR_DIR)

    logger.info(f"Vector index built and saved to {VECTOR_DIR}")


if __name__ == "__main__":
    build_index()
