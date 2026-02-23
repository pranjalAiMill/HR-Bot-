# import json, os, re, requests
# from config.llm_factory import get_llm
# from utils.logger import get_logger

# logger = get_logger("approve")
# llm = get_llm()
# MCP_URL = "http://localhost:9000/leave/approve"


# def approve_agent(state):
#     logger.info("Approve agent started")

#     user = state.get("user", {})
#     role = user.get("role")
#     hr_emp_id = user.get("emp_id")

#     if role != "hr":
#         return {"action_status": "Unauthorized: Only HR can approve leaves."}

#     query = state["query"]

#     prompt = f"""
# Extract the employee ID from this HR approval query.
# Query: "{query}"

# Return STRICT JSON:
# {{"emp_id": "E107"}}

# Return ONLY JSON, no explanation, no markdown.
# """
#     raw = llm.invoke(prompt).content.strip()
#     logger.info(f"Approve LLM raw output: {raw}")

#     # Strip markdown if LLM wraps in backticks
#     raw = raw.replace("```json", "").replace("```", "").strip()

#     try:
#         payload = json.loads(raw)
#     except json.JSONDecodeError:
#         logger.error(f"JSON parse failed: {raw}")
#         return {"action_status": "Could not parse approval request."}

#     if "emp_id" not in payload:
#         return {"action_status": "Could not find employee ID. Please say 'approve leave for E107'."}

#     payload["hr_emp_id"] = hr_emp_id

#     logger.info(f"Calling MCP approve with payload: {payload}")

#     response = requests.post(
#         MCP_URL,
#         json=payload,
#         headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
#     )
#     response.raise_for_status()

#     return {"action_status": response.json().get("message", "Leave approved successfully")}


import json, os, re, requests
from datetime import date, timedelta
from config.llm_factory import get_llm
from utils.logger import get_logger

logger = get_logger("approve")
llm = get_llm()

MCP_LEAVE_APPROVE_URL     = "http://localhost:9000/leave/approve"
MCP_TIMESHEET_APPROVE_URL = "http://localhost:9000/timesheet/approve"


def get_week_start(d: date) -> str:
    return (d - timedelta(days=d.weekday())).isoformat()


def approve_agent(state):
    logger.info("Approve agent started")

    user      = state.get("user", {})
    role      = user.get("role")
    hr_emp_id = user.get("emp_id")

    if role != "hr":
        return {"action_status": "Unauthorized: Only HR can approve requests."}

    query = state["query"].lower()

    # Extract emp_id safely via regex
    match = re.search(r'\bE\d{3,}\b', query, re.IGNORECASE)
    if match:
        emp_id = match.group(0).upper()
        logger.info(f"emp_id extracted via regex: {emp_id}")
    else:
        return {"action_status": "Could not find employee ID. Please say 'approve leave for E107'."}

    # ── Decide which module to call ──
    if "timesheet" in query:
        url   = MCP_TIMESHEET_APPROVE_URL
        today = date.today()

        # ✅ Handle "last week" vs current week
        if "last week" in query:
            last_week  = today - timedelta(days=7)
            week_start = get_week_start(last_week)
            logger.info(f"Approving LAST WEEK timesheets: {week_start}")
        else:
            week_start = get_week_start(today)
            logger.info(f"Approving CURRENT WEEK timesheets: {week_start}")

        payload = {
            "emp_id":     emp_id,
            "week_start": week_start,
            "hr_emp_id":  hr_emp_id
        }

    else:
        url     = MCP_LEAVE_APPROVE_URL
        payload = {
            "emp_id":    emp_id,
            "hr_emp_id": hr_emp_id
        }

    logger.info(f"Calling MCP approve at {url} with payload: {payload}")

    response = requests.post(
        url,
        json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )

    response.raise_for_status()

    return {
        "action_status": response.json().get("message", "Approval successful.")
    }