from utils.logger import get_logger
from utils.vector_store import get_retriever
from config.llm_factory import get_llm

import math

logger = get_logger("rag")
llm = get_llm()

# ─────────────────────────────────────────
# Cross-Encoder reranker (loaded once)
# ─────────────────────────────────────────
try:
    from sentence_transformers import CrossEncoder
    _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    logger.info("Cross-encoder reranker loaded successfully")
except Exception:
    _cross_encoder = None
    logger.warning("Cross-encoder not available — reranking will be skipped")

# Threshold after sigmoid normalization (0.0 – 1.0 scale)
RERANK_THRESHOLD = 0.95


def sigmoid(x: float) -> float:
    """Map a raw cross-encoder score to [0, 1]."""
    return 1.0 / (1.0 + math.exp(-x))


def rerank_docs(query: str, docs: list) -> list:
    """
    Score every retrieved chunk with the cross-encoder,
    normalise with sigmoid, then keep only chunks whose
    normalised score >= RERANK_THRESHOLD.

    Falls back to the original list when the cross-encoder
    is unavailable or all chunks are filtered out.
    """
    if _cross_encoder is None or not docs:
        return docs

    pairs = [(query, d.page_content) for d in docs]
    raw_scores = _cross_encoder.predict(pairs)           # numpy array

    scored = []
    for doc, raw in zip(docs, raw_scores):
        norm_score = sigmoid(float(raw))
        doc.metadata["rerank_score_raw"]  = round(float(raw), 4)
        doc.metadata["rerank_score_norm"] = round(norm_score, 4)
        scored.append((norm_score, doc))
        logger.info(
            f"Chunk '{doc.metadata.get('policy','?')} — "
            f"{doc.metadata.get('section','?')}' | "
            f"raw={raw:.4f} | sigmoid={norm_score:.4f}"
        )

    # Sort highest-score first
    scored.sort(key=lambda x: x[0], reverse=True)

    # Apply threshold
    filtered = [doc for score, doc in scored if score >= RERANK_THRESHOLD]

    if not filtered:
        logger.warning(
            f"All chunks scored below threshold {RERANK_THRESHOLD}. "
            "Falling back to top-1 chunk to avoid empty context."
        )
        # Graceful fallback: return the single best chunk so the
        # summariser always has *something* to work with.
        filtered = [scored[0][1]]

    logger.info(
        f"Reranking: {len(docs)} retrieved → "
        f"{len(filtered)} passed threshold {RERANK_THRESHOLD}"
    )
    return filtered


# ─────────────────────────────────────────
# RAG agent
# ─────────────────────────────────────────

def rag_agent(state):
    logger.info("RAG agent started")

    query = state["query"]
    chat_history = state.get("chat_history", [])

    # ── 1. Rewrite vague follow-up queries ──────────────────────────────────
    vague_triggers = [
        "what is the policy", "tell me more", "explain that",
        "what does it say", "elaborate", "the policy", "more details"
    ]
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

    # ── 2. First-stage retrieval (vector similarity / MMR) ──────────────────
    retriever = get_retriever()
    docs = retriever.invoke(query)
    logger.info(f"Retrieved chunks (before reranking): {len(docs)}")

    # ── 3. Cross-encoder reranking + sigmoid threshold ───────────────────────
    docs = rerank_docs(query, docs)
    logger.info(f"Chunks after reranking: {len(docs)}")

    # ── 4. Build context for the summariser ─────────────────────────────────
    context = "\n\n".join(d.page_content for d in docs)
    citations = [
        f"{d.metadata.get('policy', 'Unknown')} — {d.metadata.get('section', '')}"
        for d in docs
    ]
    chunks = [d.page_content for d in docs]

    return {
        "rag_context": context,
        "policy_citations": citations,
        "rag_chunks": chunks,
    }