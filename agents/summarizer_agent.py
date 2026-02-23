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

    # 🆕 Build history context
    chat_history = state.get("chat_history", [])
    history_text = ""
    if chat_history:
        recent = chat_history[-6:]
        history_text = "\n".join(
            f"{r.upper()}: {c}" for r, c in recent
        )

    logger.info(
    f"State snapshot → rag={'yes' if rag_context else 'no'}, "
    f"sql={'yes' if sql_result is not None else 'no'}, "
    f"action={'yes' if action_status else 'no'}, "
    f"history_turns={len(chat_history)}"
)

    prompt = f"""
You are an expert HR assistant.

Using ONLY the information provided below, answer the user's query
in a concise, professional HR tone.

Conversation history (use to resolve references and recall previous answers):
{history_text if history_text else "None"}

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
- Don't add extra details unless directly relateds
- FIRST check conversation history to understand what the user is referring to
- If the query is vague like "what is the policy", "tell me more", "explain that" 
identify the topic from history and answer about THAT topic
- If history clearly shows the user was asking about casual leave, 
and now asks "what is the policy" → answer about casual leave policy
- Use history to resolve: "it", "that", "the policy", "same", "again", "more"
- Do NOT fetch unrelated policies when history gives clear context
- Answer ONLY the current query in context of history
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
    # Only show leave_policy related citations if answer is about leave
    # Filter to unique policy names only
        seen_policies = set()
        filtered_citations = []
        filtered_chunks = []
        
        for i, citation in enumerate(citations):
            policy_name = citation.split(" — ")[0].strip()
            if policy_name not in seen_policies:
                seen_policies.add(policy_name)
                filtered_citations.append(citation)
                filtered_chunks.append(rag_chunks[i] if i < len(rag_chunks) else "")

        answer += "\n\n---\n**📄 Sources**\n\n"
        answer += "| Policy Name | Policy Content |\n"
        answer += "|-------------|----------------|\n"

        for i, citation in enumerate(filtered_citations[:4]):  # max 3 sources
            chunk_content = filtered_chunks[i].strip().replace("\n", " ")[:200]
            if len(filtered_chunks[i].strip()) > 200:
                chunk_content += "..."
            chunk_content = chunk_content.replace("|", "\\|")
            citation_clean = str(citation).replace("|", "\\|")
            answer += f"| {citation_clean} | {chunk_content} |\n"

    logger.info("Summarizer agent finished successfully")
    
    # ✅ LangGraph-safe return
    return {"final_answer": answer}
