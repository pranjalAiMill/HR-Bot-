import json, os, requests
from datetime import date
from config.llm_factory import get_llm
from utils.logger import get_logger

logger = get_logger("reject")
llm = get_llm()
MCP_URL = "http://localhost:9000/leave/reject"


def reject_agent(state):
    logger.info("Reject agent started")

    user = state.get("user", {})
    role = user.get("role")
    hr_emp_id = user.get("emp_id")
    today = date.today().isoformat()

    if role != "hr":
        return {"action_status": "Unauthorized: Only HR can reject leaves."}

    query = state["query"]

    prompt = f"""
Extract rejection details from this HR query.
Today's date is: {today}

Query: "{query}"

Return STRICT JSON with only the fields clearly mentioned:
{{
  "emp_id": "E107",
  "days": 2,
}}

Rules:
- emp_id: employee ID like E007, E101 (include if mentioned)
- days: number of days if mentioned
- start_date: ONLY include if a specific date explicitly mentioned
- Return ONLY JSON, no markdown, no backticks
"""

    raw = llm.invoke(prompt).content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    logger.info(f"Reject LLM raw output: {raw}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"action_status": "Could not parse rejection request."}

    if not payload.get("emp_id"):
        return {"action_status": "Please specify which employee's leave to reject. Example: 'reject leave for E107'"}

    payload["hr_emp_id"] = hr_emp_id

    response = requests.post(
        MCP_URL,
        json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )
    response.raise_for_status()

    return {"action_status": response.json().get("message", "Leave rejected")}