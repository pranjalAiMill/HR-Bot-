# import json
# import os
# import requests
# from datetime import date

# from config.llm_factory import get_llm
# from utils.logger import get_logger

# logger = get_logger("action")

# llm = get_llm()
# MCP_URL = "http://localhost:9000/leave/apply"


# def action_agent(state):
#     logger.info("Action agent started")
#     logger.info(f"Incoming query: {state['query']}")

#     today = date.today().isoformat()

#     prompt = f"""
# You are an Action Extraction Agent for an HR system.

# Today’s date is: {today}

# User query:
# "{state['query']}"

# If and ONLY IF the user is requesting a leave action,
# return STRICT JSON in the following format:

# {{
#   "emp_id": "E102",
#   "start_date": "YYYY-MM-DD",
#   "days": 1
# }}

# Rules:
# - Resolve relative dates like "tomorrow", "next Monday"
# - Use ISO-8601 date format
# - No markdown
# - No explanation
# - Return ONLY JSON
# - If no action is requested, return null
# """

#     raw = llm.invoke(prompt).content.strip()
#     logger.info(f"Raw LLM output: {raw}")

#     if raw.lower() == "null":
#         logger.info("No actionable intent detected")
#         return {"action_status": None}

#     try:
#         payload = json.loads(raw)
#     except json.JSONDecodeError:
#         raise RuntimeError(f"Invalid JSON from action agent: {raw}")
    
#     # 🔒 Resolve emp_id from trusted user context
#     payload["emp_id"] = payload.get("emp_id") or state["user"].get("emp_id")

#     required_keys = {"emp_id", "start_date", "days"}
#     if not required_keys.issubset(payload):
#         raise RuntimeError(f"Incomplete action payload: {payload}")

#     logger.info(f"Parsed action payload: {payload}")
#     logger.info("Calling MCP server to apply leave")

#     response = requests.post(
#         MCP_URL,
#         json=payload,
#         headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
#     )

#     logger.info(f"MCP HTTP status: {response.status_code}")
#     logger.info(f"MCP response body: {response.text}")

#     response.raise_for_status()

#     return {
#         "action_status": response.json().get("message", "Leave applied successfully")
#     }

import json
import os
import re
import requests
from datetime import date

from config.llm_factory import get_llm
from utils.logger import get_logger

logger = get_logger("action")

llm = get_llm()
MCP_URL = "http://localhost:9000/leave/apply"


def extract_emp_id_from_query(query: str):
    """
    Extract emp_id like E101, E102 from query text.
    """
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

Today’s date is: {today}

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
        # Employees can apply ONLY for themselves
        payload["emp_id"] = user_emp_id

    elif role == "hr":
        # HR can apply for others if explicitly mentioned
        payload["emp_id"] = mentioned_emp_id or user_emp_id

    else:
        raise RuntimeError("Invalid user role")

    required_keys = {"emp_id", "start_date", "days"}
    if not required_keys.issubset(payload):
        raise RuntimeError(f"Incomplete action payload: {payload}")

    logger.info(f"Final enforced action payload: {payload}")
    logger.info("Calling MCP server to apply leave")

    response = requests.post(
        MCP_URL,
        json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )

    logger.info(f"MCP HTTP status: {response.status_code}")
    logger.info(f"MCP response body: {response.text}")

    response.raise_for_status()

    mcp_resp = response.json()
    return {
        "action_status": f"{mcp_resp.get('message', 'Leave applied successfully')}. Remaining leave: {mcp_resp.get('remaining_balance', 'N/A')}"
    }
