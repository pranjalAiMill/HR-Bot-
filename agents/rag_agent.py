from utils.logger import get_logger
from utils.vector_store import get_retriever

logger = get_logger("rag")


def rag_agent(state):
    logger.info("RAG agent started")
    logger.info(f"Query: {state['query']}")

    retriever = get_retriever()
    docs = retriever.invoke(state["query"])
    # Debug: Check metadata
    if docs:
        logger.info(f"First doc metadata: {docs[0].metadata}")

    logger.info(f"Retrieved chunks: {len(docs)}")

    context = "\n\n".join(d.page_content for d in docs)
    
    # ✅ Store both policy name and section together
    citations = [
        f"{d.metadata.get('policy', 'Unknown')} — {d.metadata.get('section', '')}"
        for d in docs
    ]
    logger.info(f"Citations created: {len(citations)}")
    logger.info(f"First citation: {citations[0] if citations else 'None'}")

    # ✅ Store chunks separately for table display
    chunks = [d.page_content for d in docs]

    return {
        "rag_context": context,
        "policy_citations": citations,
        "rag_chunks": chunks   # ← add this to state
    }