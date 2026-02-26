import json
import os
import requests

from config.llm_factory import get_llm
from utils.logger import get_logger

logger = get_logger("service_request_agent")
llm    = get_llm()

MCP_SUBMIT_URL = os.getenv("MCP_SERVICE_REQUEST_SUBMIT_URL", "http://localhost:9000/service-request/submit")

VALID_CATEGORIES = {"software", "hardware", "asset", "access", "other"}


def service_request_agent(state):
    logger.info("Service Request agent started")

    user   = state.get("user", {})
    emp_id = user.get("emp_id")
    query  = state["query"]

    if not emp_id:
        return {"action_status": "Could not determine your employee ID."}

    # ── EMPLOYEE: SUBMIT ─────────────────────────────────────────────────────
    prompt = f"""
You are a Service Request Extraction Agent for an HR system.

User query: "{query}"

Extract the service request details and return STRICT JSON:
{{
  "category": "hardware",
  "item": "headphone",
  "reason": "to attend meetings clearly"
}}

Category must be exactly one of: software, hardware, asset, access, other
- software  → any app, tool, license, IDE, or digital subscription
- hardware  → any physical device or equipment the employee needs
- asset     → company assets like ID card, access card, locker, desk
- access    → system permissions, VPN, portal access
- other     → anything that doesn't fit above

Rules:
- item: the exact thing the user is requesting, be specific
- reason: the user's stated reason, or infer a short sensible reason from context
- If this is NOT a request for something, return null
- No markdown, no explanation, ONLY JSON
"""

    raw = llm.invoke(prompt).content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    logger.info(f"Service request LLM output: {raw}")

    if raw.lower() == "null":
        return {"action_status": None}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "action_status": (
                "Could not understand your request. "
                "Please say something like: 'I need a headphone to attend meetings' "
                "or 'request Zoom license for client calls'."
            )
        }

    if not payload.get("item"):
        return {"action_status": "Please mention what you need. E.g. 'I need a MacBook Pro for development'"}
    if not payload.get("reason"):
        return {"action_status": "Please mention why you need it. E.g. 'I need Zoom license for client calls'"}
    if payload.get("category") not in VALID_CATEGORIES:
        payload["category"] = "other"

    payload["emp_id"] = emp_id  # always from trusted session context, never from query

    logger.info(f"Submitting service request payload: {payload}")

    response = requests.post(
        MCP_SUBMIT_URL, json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )

    if response.status_code in (400, 403, 404):
        try:
            msg = response.json().get("error", response.text)
        except Exception:
            msg = response.text or "Request rejected."
        return {"action_status": msg}

    response.raise_for_status()
    return {"action_status": response.json().get("message", "Service request submitted successfully.")}