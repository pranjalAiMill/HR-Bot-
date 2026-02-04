from config.llm_factory import get_llm
from utils.logger import get_logger

logger = get_logger("summarizer")
llm = get_llm()


def summarizer_agent(state):
    logger.info("Summarizer agent started")

    # 🔴 Hard stop on errors (no LLM call)
    if "error" in state:
        logger.warning(f"Summarizer received error: {state['error']}")
        return {
            "final_answer": f"⚠️ {state['error']['message']}"
        }

    query = state.get("query")
    rag_context = state.get("rag_context")
    sql_result = state.get("sql_result")
    action_status = state.get("action_status")
    citations = state.get("citations") or []

    logger.info(
        "State snapshot → "
        f"rag={'yes' if rag_context else 'no'}, "
        f"sql={'yes' if sql_result is not None else 'no'}, "
        f"action={'yes' if action_status else 'no'}, "
        f"citations={len(citations)}"
    )

    prompt = f"""
You are an expert HR assistant.

Using ONLY the information provided below, answer the user's query
in a concise, professional HR tone.

User Query:
{query}

Policy Context:
{rag_context}

SQL Result:
{sql_result}

Action Result:
{action_status}

Rules:
- If a section is missing or empty, ignore it.
- Do NOT make up information.
- Do NOT assume facts not present in the context.
- Keep the response concise and factual.
- Do NOT mention SQL, databases, or system internals.
"""

    logger.info(f"Summarizer prompt length: {len(prompt)} characters")

    answer = llm.invoke(prompt).content.strip()
    logger.info("LLM summarization completed")

    if citations:
        logger.info("Appending policy citations to answer")
        answer += "\n\nReferences:\n" + "\n".join(citations)

    logger.info("Summarizer agent finished successfully")

    # ✅ LangGraph-safe return
    return {"final_answer": answer}
