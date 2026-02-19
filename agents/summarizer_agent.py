# from config.llm_factory import get_llm
# from utils.logger import get_logger

# logger = get_logger("summarizer")
# llm = get_llm()


# def summarizer_agent(state):
#     logger.info("Summarizer agent started")

#     # 🔴 Hard stop on errors (no LLM call)
#     if "error" in state:
#         logger.warning(f"Summarizer received error: {state['error']}")
#         return {
#             "final_answer": f"⚠️ {state['error']['message']}"
#         }

#     query = state.get("query")
#     rag_context = state.get("rag_context")
#     sql_result = state.get("sql_result")
#     action_status = state.get("action_status")
#     citations = state.get("citations") or []

#     logger.info(
#         "State snapshot → "
#         f"rag={'yes' if rag_context else 'no'}, "
#         f"sql={'yes' if sql_result is not None else 'no'}, "
#         f"action={'yes' if action_status else 'no'}, "
#         f"citations={len(citations)}"
#     )

#     prompt = f"""
# You are an expert HR assistant.

# Using ONLY the information provided below, answer the user's query
# in a concise, professional HR tone.

# User Query:
# {query}

# Policy Context:
# {rag_context}

# SQL Result:
# {sql_result}

# Action Result:
# {action_status}

# Rules:
# - If a section is missing or empty, ignore it.
# - Do NOT make up information.
# - Do NOT assume facts not present in the context.
# - Keep the response concise and factual.
# - Do NOT mention SQL, databases, or system internals.
# """

#     logger.info(f"Summarizer prompt length: {len(prompt)} characters")

#     answer = llm.invoke(prompt).content.strip()
#     logger.info("LLM summarization completed")

#     if citations:
#         logger.info("Appending policy citations to answer")
#         answer += "\n\nReferences:\n" + "\n".join(citations)

#     logger.info("Summarizer agent finished successfully")

#     # ✅ LangGraph-safe return
#     return {"final_answer": answer}


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
    # Get citations from state (using correct key)
    citations = state.get("policy_citations") or []
    rag_chunks = state.get("rag_chunks", [])

    logger.info(f"Citations in summarizer: {len(citations)}")
    logger.info(f"RAG chunks in summarizer: {len(rag_chunks)}")

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
- Do not dump entire documents unless explicitly requested.
- Do NOT mention SQL, databases, or system internals.
- Answer only what the user asked
- Keep it concise and relevant
- Don't add extra details unless directly related
"""

    logger.info(f"Summarizer prompt length: {len(prompt)} characters")

    resp = llm.invoke(prompt)
    content = resp.content

    if isinstance(content, list):
        # Gemini can return a list of parts; convert to a string safely.
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and "text" in p:
                parts.append(p["text"])
            else:
                parts.append(str(p))
        answer = "\n".join(parts).strip()
    else:
        answer = str(content).strip()
    logger.info("LLM summarization completed")

    logger.info(f"Citations in summarizer: {len(citations)}")
    logger.info(f"RAG chunks in summarizer: {len(rag_chunks)}")

    if citations:
        logger.info(f"First citation: {citations[0]}")
        # rag_chunks = state.get("rag_chunks", [])
        
        answer += "\n\n---\n**📄 Sources**\n\n"
        answer += "| Policy Name | Policy Content |\n"
        answer += "|-------------|----------------|\n"
        
        seen = set()
        for i, citation in enumerate(citations[:5]):
            if not citation or citation in seen:
                continue
            seen.add(citation)
            
            chunk_content = ""
            if i < len(rag_chunks):
                chunk_content = rag_chunks[i].strip().replace("\n", " ")[:200]
                if len(rag_chunks[i].strip()) > 200:
                    chunk_content += "..."
            
            chunk_content = chunk_content.replace("|", "\\|")
            citation_clean = str(citation).replace("|", "\\|")
            
            answer += f"| {citation_clean} | {chunk_content} |\n"

    logger.info("Summarizer agent finished successfully")
    
    # ✅ LangGraph-safe return
    return {"final_answer": answer}
