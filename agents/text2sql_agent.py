# from sqlalchemy import text

# from config.llm_factory import get_llm
# from utils.db_loader import build_db
# from utils.schema_prompt import build_schema_prompt
# from utils.logger import get_logger

# logger = get_logger("text2sql")

# llm = get_llm()
# engine = build_db()


# def text2sql_agent(state):
#     logger.info("Text2SQL agent started")
#     logger.info(f"User query: {state['query']}")

#     schema_prompt = build_schema_prompt()

#     prompt = f"""
# You are an expert Text-to-SQL system.

# Use ONLY the database schema provided below.
# Do NOT invent tables or columns.

# {schema_prompt}

# Rules:
# - Generate only SELECT queries
# - Use exact table and column names
# - No explanations
# - No markdown
# - No comments
# - Queries on leave_log must always be filtered by emp_id
# - Do not return data for other employees

# User question:
# {state['query']}
# """

#     sql = llm.invoke(prompt).content.strip()
#     logger.info(f"Generated SQL: {sql}")

#     if not sql.lower().startswith("select"):
#         logger.warning("Non-SELECT query generated, skipping execution")
#         return {}

#     try:
#         with engine.connect() as conn:
#             rows = conn.execute(text(sql)).fetchall()
#     except Exception:
#         logger.exception("SQL execution failed")
#         raise

#     logger.info(f"Rows returned: {len(rows)}")
#     if rows:
#         logger.info(f"Sample row: {rows[0]}")

#     return {"sql_result": rows}


from sqlalchemy import text

from config.llm_factory import get_llm
from utils.db_loader import build_db
from utils.schema_prompt import build_schema_prompt
from utils.logger import get_logger

logger = get_logger("text2sql")

llm = get_llm()
engine = build_db()


def text2sql_agent(state):
    logger.info("Text2SQL agent started")
    logger.info(f"User query: {state['query']}")

    user = state.get("user", {})
    emp_id = user.get("emp_id")
    role = user.get("role", "employee")

    if not emp_id:
        return {
            "error": {
                "code": "NO_USER_CONTEXT",
                "message": "User identity could not be determined."
            }
        }

    schema_prompt = build_schema_prompt()

    prompt = f"""
You are an expert Text-to-SQL system.

Use ONLY the database schema provided below.
Do NOT invent tables or columns.

{schema_prompt}

User context:
- role = {role}
- emp_id = {emp_id}

Rules:
- Generate ONLY SELECT queries
- Use exact table and column names
- No explanations
- No markdown
- No comments
- If role = employee:
    - Restrict results to emp_id = '{emp_id}'
    - Do NOT return data for other employees
- Queries on leave_log MUST always be filtered by emp_id
- Queries on leave_log MUST always be filtered by emp_id
- If asked about multiple pieces of information, use separate queries or JOIN tables
- DO NOT concatenate multiple SELECT statements

User question:
{state['query']}
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
        sql = "\n".join(parts).strip()
    else:
        sql = str(content).strip()
    logger.info(f"Generated SQL: {sql}")

    if not sql.lower().startswith("select"):
        logger.warning("Non-SELECT query generated, skipping execution")
        return {}

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
    except Exception:
        logger.exception("SQL execution failed")
        raise

    logger.info(f"Rows returned: {len(rows)}")
    if rows:
        logger.info(f"Sample row: {rows[0]}")

    return {"sql_result": rows}
