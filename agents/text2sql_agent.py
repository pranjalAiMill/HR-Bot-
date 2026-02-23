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
IMPORTANT: Do NOT query the chat_history table or the timesheets table.
Use ONLY the database schema provided below.
Do NOT invent tables or columns.

{schema_prompt}

User context:
- role = {role}
- emp_id = {emp_id}

Rules:
- Generate ONLY a single SELECT query
- Use exact table and column names from the schema above
- No explanations, no markdown, no comments
- DO NOT concatenate multiple SELECT statements

Access control:
- If role = employee:
    - Restrict ALL results to emp_id = '{emp_id}'
    - Do NOT return data for other employees
    - Applies to: leave_log, timesheet_log, payslips, etc.
- If role = hr:
    - Can query ALL employees — do NOT filter by emp_id unless specifically asked
    - leave_log status values are exactly: 'PENDING_HR' or 'APPROVED'
    - timesheet_log status values are exactly: 'PENDING_HR' or 'APPROVED'

Timesheet rules (IMPORTANT):
- For ANY query about timesheets → ALWAYS use timesheet_log, NEVER use timesheets table
- timesheet_log columns: id, emp_id, project_id, date, hours, week_start, week_end,
  status, jira_issue_key, approved_by, approved_at, created_at, updated_at
- There is NO 'project' column in timesheet_log — use project_id
- To get the project name, JOIN with projects table: LEFT JOIN projects p ON tl.project_id = p.project_id
- To get the employee name, JOIN with employees table: LEFT JOIN employees e ON tl.emp_id = e.emp_id
 For ALL timesheet queries:
- You MUST include tl.emp_id as employee_id in SELECT
- You MUST include e.name as employee_name
- You MUST include p.name as project
- Never omit employee_id
- Always show tl.emp_id, employee name (e.name), project name (p.name) in timesheet queries
- Example:
SELECT 
    tl.emp_id AS employee_id,
    e.name AS employee_name,
    p.name AS project,
    tl.date,
    tl.hours,
    tl.status,
    tl.jira_issue_key
FROM timesheet_log tl
LEFT JOIN employees e ON tl.emp_id = e.emp_id
LEFT JOIN projects p ON tl.project_id = p.project_id

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