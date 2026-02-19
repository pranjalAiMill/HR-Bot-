# import json

# from config.llm_factory import get_llm
# from utils.logger import get_logger

# logger = get_logger("planner")

# llm = get_llm()

# ALLOWED_STEPS = {"RAG", "SQL", "ACTION", "SUMMARY"}


# def planner_agent(state):
#     query = state["query"]
#     q = query.lower()

#     logger.info("Planner agent started")
#     logger.info(f"Incoming query: {query}")

#     # ✅ HARD RULES FIRST (NO LLM)
#     if "policy" in q or "leave policy" in q or "casual leave" in q:
#         steps = ["RAG"]
#         logger.info("Matched POLICY rule → RAG + SUMMARY")
#         logger.info(f"Planner steps decided: {steps}")
#         return {"steps": steps}

#     if "apply" in q or "cancel" in q or "update leave" in q:
#         steps = ["ACTION"]
#         logger.info("Matched ACTION rule → ACTION + SUMMARY")
#         logger.info(f"Planner steps decided: {steps}")
#         return {"steps": steps}

#     if "balance" in q or "how many" in q:
#         steps = ["SQL"]
#         logger.info("Matched DATA rule → SQL + SUMMARY")
#         logger.info(f"Planner steps decided: {steps}")
#         return {"steps": steps}

#     # 🔁 LLM FALLBACK (only when rules do not match)
#     logger.warning("No hard rule matched — falling back to LLM planner")

#     prompt = f"""
# You are an expert HR with over 20 years of experience.
# You have to decide execution steps for the HR query:
# "{query}"

# Return STRICT JSON array using only:
# RAG, SQL, ACTION

# Rules:
# - No markdown
# - No explanation
# - Return ONLY JSON
# Example:
# ["RAG"]
# """

#     raw = llm.invoke(prompt).content.strip()
#     logger.info(f"Raw LLM planner output: {raw}")

#     try:
#         steps = json.loads(raw)
#     except json.JSONDecodeError:
#         logger.error("Planner LLM returned invalid JSON")
#         logger.error(f"Invalid planner output: {raw}")
#         raise RuntimeError(f"Invalid planner JSON: {raw}")

#     # 🔐 Validate steps
#     for s in steps:
#         if s not in ALLOWED_STEPS:
#             logger.error(f"Planner returned invalid step: {s}")
#             raise RuntimeError(f"Invalid planner step: {s}")

#     logger.info("Planner LLM output validated successfully")
#     logger.info(f"Planner steps decided: {steps}")

#     return {"steps": steps}


from utils.logger import get_logger
from config.llm_factory import get_llm
import json

logger = get_logger("planner")
llm = get_llm()

ALLOWED_STEPS = {"RAG", "SQL", "ACTION"}

def planner_agent(state):
    logger.info("Planner agent started")

    query = state["query"]
    q = query.lower()

    user = state.get("user", {})
    role = user.get("role", "employee")
    emp_id = user.get("emp_id")

    logger.info(f"Incoming query: {query} | role={role} | emp_id={emp_id}")

    # ----------------------------
    # 🔒 RBAC RULES (NO ROUTING)
    # ----------------------------

    # Salary access
    if "salary" in q:
        if role != "hr":
            # Employee can only see own salary
            if not any(k in q for k in ["my", "mine"]) and emp_id not in q:
                return {
                    "steps": [],
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "You can only view your own salary."
                    }
                }

    # Leave application for others
    if "apply" in q and "for e" in q and role != "hr":
        if emp_id not in q:
            return {
                "steps": [],
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "You can only apply leave for yourself."
                }
            }
    
    # ----------------------------
    # ✅ DETERMINISTIC ROUTING
    # ----------------------------

    if "policy" in q or "leave policy" in q:
        return {"steps": ["RAG"]}

    if "apply leave" in q:
        return {"steps": ["ACTION"]}

    if "balance" in q or "salary" in q:
        return {"steps": ["SQL"]}


    # ----------------------------
    # 🔁 LLM FALLBACK (RARE)
    # ----------------------------

    logger.warning("No hard rule matched — falling back to LLM planner")
    
    prompt = f"""
You are an expert HR with over 20 years of experience.
You have to decide execution steps for the HR query:
"{query}"

Return STRICT JSON array using only:
- RAG: Use when the answer comes from a policy document, handbook, or 
       company rules. The query asks about how something works, what 
       the rules are, what consequences exist, or what policies apply.
       
- SQL: Use when the answer requires looking up a specific employee's 
       personal data from a database — their own records, numbers, 
       or history that is unique to them.
       
- ACTION: Use ONLY when the user is explicitly requesting to perform 
          an operation — submitting, applying, cancelling, or booking 
          something right now.

Critical distinction for the word "apply":
- "apply leave", "apply for leave", "I want to apply" → ACTION
- "which policies apply", "what rules apply", "consequences apply" → RAG

Decision rule:
- Query asks about a RULE, POLICY, or CONSEQUENCE, which policies apply → RAG
- If the query is about ME / MY personal data → SQL  
- If the query wants to DO something right now → ACTION
- When in doubt → RAG    
 
Rules:
- No markdown
- No explanation
- Return ONLY JSON
Example:
["RAG"]
"""

    resp = llm.invoke(prompt)
    content = resp.content

    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and "text" in p:
                parts.append(p["text"])
            else:
                parts.append(str(p))
        planner_json = "\n".join(parts).strip()
    else:
        planner_json = str(content).strip()

    steps = json.loads(planner_json)

    for s in steps:
        if s not in ALLOWED_STEPS:
            raise RuntimeError(f"Invalid planner step: {s}")

    return {"steps": steps}

