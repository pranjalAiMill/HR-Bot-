import json
import os
import re
import requests
from datetime import date

from config.llm_factory import get_llm
from utils.logger import get_logger

logger = get_logger("action")

llm = get_llm()
MCP_URL = os.getenv("MCP_LEAVE_APPLY_URL", "http://localhost:9000/leave/apply")


def extract_emp_id_from_query(query: str):
    match = re.search(r"\bE\d{3}\b", query.upper())
    return match.group(0) if match else None


def action_agent(state):
    logger.info("Action agent started")
    logger.info(f"Incoming query: {state['query']}")

    user = state.get("user", {})
    user_emp_id = user.get("emp_id")
    role = user.get("role", "employee")

    if not user_emp_id:
        raise RuntimeError("User context missing emp_id")

    today = date.today().isoformat()

    prompt = f"""
You are an Action Extraction Agent for an HR system.

Today's date is: {today}

User query:
"{state['query']}"

If and ONLY IF the user is requesting a leave action,
return STRICT JSON in the following format:

{{
  "start_date": "YYYY-MM-DD",
  "days": 1
}}

Rules:
- Do NOT guess emp_id
- Resolve relative dates like "tomorrow", "next Monday"
- Use ISO-8601 date format
- No markdown
- No explanation
- Return ONLY JSON
- If no action is requested, return null
"""

    raw = llm.invoke(prompt).content.strip()
    logger.info(f"Raw LLM output: {raw}")

    if raw.lower() == "null":
        logger.info("No actionable intent detected")
        return {"action_status": None}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"Invalid JSON from action agent: {raw}")

    # 🔐 AUTHORITATIVE emp_id resolution
    mentioned_emp_id = extract_emp_id_from_query(state["query"])

    if role == "employee":
        payload["emp_id"] = user_emp_id
    elif role == "hr":
        payload["emp_id"] = mentioned_emp_id or user_emp_id
    else:
        raise RuntimeError("Invalid user role")

    required_keys = {"emp_id", "start_date", "days"}
    if not required_keys.issubset(payload):
        raise RuntimeError(f"Incomplete action payload: {payload}")

    logger.info(f"Final enforced action payload: {payload}")
    logger.info("Calling MCP server to apply leave")

    # ✅ THIS WAS MISSING — the actual HTTP call
    response = requests.post(
        MCP_URL,
        json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )

    logger.info(f"MCP HTTP status: {response.status_code}")
    logger.info(f"MCP response body: {response.text}")

    if response.status_code in (400, 404):
        try:
            error_msg = response.json().get("error", "Request failed.")
        except Exception:
            # Fallback if response is still HTML
            match = re.search(r"<p>(.*?)</p>", response.text)
            error_msg = match.group(1) if match else "Request failed."
        return {"action_status": error_msg}

    response.raise_for_status()

    mcp_resp = response.json()
    return {
        "action_status": mcp_resp.get('message', 'Leave applied successfully')
    }