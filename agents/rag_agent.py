from utils.logger import get_logger
from utils.vector_store import get_retriever

logger = get_logger("rag")


def rag_agent(state):
    logger.info("RAG agent started")
    logger.info(f"Query: {state['query']}")

    retriever = get_retriever()
    docs = retriever.invoke(state["query"])

    logger.info(f"Retrieved chunks: {len(docs)}")

    context = "\n".join(d.page_content for d in docs)
    citations = [d.metadata.get("section") for d in docs]

    return {
        "rag_context": context,
        "citations": citations
    }
