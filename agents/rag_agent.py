from utils.logger import get_logger
from utils.vector_store import get_retriever
from config.llm_factory import get_llm

logger = get_logger("rag")
llm = get_llm()


def rag_agent(state):
    logger.info("RAG agent started")

    query = state["query"]
    chat_history = state.get("chat_history", [])

    # ✅ Rewrite vague queries using chat history
    vague_triggers = ["what is the policy", "tell me more", "explain that", 
                      "what does it say", "elaborate", "the policy", "more details"]
    
    is_vague = any(t in query.lower() for t in vague_triggers)

    if is_vague and chat_history:
        recent = chat_history[-6:]
        history_text = "\n".join(f"{r.upper()}: {c}" for r, c in recent)
        
        rewrite_prompt = f"""
Given this conversation history:
{history_text}

The user now asks: "{query}"

Rewrite this as a specific, standalone search query that captures what the user is actually asking about.
Return ONLY the rewritten query, nothing else.
"""
        rewritten = llm.invoke(rewrite_prompt).content.strip()
        logger.info(f"Rewritten query: '{query}' → '{rewritten}'")
        query = rewritten

    logger.info(f"Final search query: {query}")

    retriever = get_retriever()
    docs = retriever.invoke(query)

    logger.info(f"Retrieved chunks: {len(docs)}")

    context = "\n\n".join(d.page_content for d in docs)
    citations = [
        f"{d.metadata.get('policy', 'Unknown')} — {d.metadata.get('section', '')}"
        for d in docs
    ]
    chunks = [d.page_content for d in docs]

    return {
        "rag_context": context,
        "policy_citations": citations,
        "rag_chunks": chunks
    }