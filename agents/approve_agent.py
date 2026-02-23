import json, os, re, requests
from config.llm_factory import get_llm
from utils.logger import get_logger
from datetime import date

logger = get_logger("approve")
llm = get_llm()
MCP_URL = "http://localhost:9000/leave/approve"


def approve_agent(state):
    logger.info("Approve agent started")
    today = date.today().isoformat()
    user = state.get("user", {})
    role = user.get("role")
    hr_emp_id = user.get("emp_id")

    if role != "hr":
        return {"action_status": "Unauthorized: Only HR can approve leaves."}

    query = state["query"]

    prompt = f"""
Extract approval details from this HR query.
Today's date is: {today}

Query: "{query}"

Return STRICT JSON with only the fields clearly mentioned:
{{
  "emp_id": "E107",
  "days": 2
}}

Rules:
- emp_id: employee ID like E007, E101 (include if mentioned)
- days: number of days if mentioned ("2 days" → 2)
- start_date: ONLY include if a specific date is explicitly mentioned
- Do NOT guess or assume any field not clearly stated
- Return ONLY JSON, no markdown, no backticks
"""

    raw = llm.invoke(prompt).content.strip()
    logger.info(f"Approve LLM raw output: {raw}")

    # Strip markdown if LLM wraps in backticks
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"JSON parse failed: {raw}")
        return {"action_status": "Could not parse approval request."}

    if "emp_id" not in payload:
        return {"action_status": "Could not find employee ID. Please say 'approve leave for E107'."}

    payload["hr_emp_id"] = hr_emp_id

    logger.info(f"Calling MCP approve with payload: {payload}")

    response = requests.post(
        MCP_URL,
        json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )
    response.raise_for_status()

    return {"action_status": response.json().get("message", "Leave approved successfully")}