import json
import os
import requests

from config.llm_factory import get_llm
from utils.logger import get_logger

logger = get_logger("onboard")
llm    = get_llm()

MCP_ONBOARD_URL = os.getenv("MCP_ONBOARD_URL", "http://localhost:9000/employee/onboard")
MCP_ADD_PROJECT_URL = os.getenv("MCP_ADD_PROJECT_URL", "http://localhost:9000/employee/project/add")
MCP_ADD_LEAVE_URL = os.getenv("MCP_ADD_LEAVE_URL", "http://localhost:9000/employee/leave/add")


def onboard_agent(state):
    logger.info("Onboard agent started")

    user      = state.get("user", {})
    role      = user.get("role")
    hr_emp_id = user.get("emp_id")

    # 🔐 HR-only gate
    if role != "hr":
        return {"action_status": "Unauthorized: Only HR can onboard new employees."}

    query = state["query"]

    prompt = f"""
You are an employee onboarding extraction agent for an HR system.

User query: "{query}"

Extract new employee details and return STRICT JSON:
{{
  "emp_id": "E108",
  "name": "Full Name",
  "department": "department name exactly as the user said",
  "email": "employee@company.com"
}}

Rules:
- emp_id: Extract exactly as mentioned (e.g. E108, HR005, FN004)
- name: Full name of the new employee
- department: Use exactly what the user said, do NOT normalize or guess
- email: Extract email if mentioned, else return null
- Return ONLY JSON, no markdown, no explanation
- If this is NOT an onboarding request, return null
"""

    raw = llm.invoke(prompt).content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    logger.info(f"Onboard LLM output: {raw}")

    if raw.lower() == "null":
        return {
            "action_status": (
                "This doesn't look like an onboarding request. "
                "Try: 'onboard new employee E108, name John Doe, "
                "department Engineering, email john@company.com'"
            )
        }

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "action_status": (
                "Could not parse onboarding details. "
                "Please provide: employee ID, name, department, and email."
            )
        }

    # ── Validate required fields before calling MCP ───────────────────────
    missing = [f for f in ["emp_id", "name", "email"] if not payload.get(f)]
    if missing:
        return {
            "action_status": (
                f"Missing details: {', '.join(missing)}. "
                "Please provide employee ID, full name, department, and email."
            )
        }

    # ── hr_emp_id always from trusted session, never from query ──────────
    payload["hr_emp_id"] = hr_emp_id

    logger.info(f"Onboard payload: {payload}")

    response = requests.post(
        MCP_ONBOARD_URL,
        json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )

    logger.info(f"MCP HTTP status: {response.status_code}")
    logger.info(f"MCP response: {response.text}")

    if response.status_code in (400, 403, 404):
        try:
            msg = response.json().get("error", response.text)
        except Exception:
            msg = response.text or "Onboarding failed."
        return {"action_status": msg}

    response.raise_for_status()
    return {
        "action_status": response.json().get("message", "Employee onboarded successfully.")
    }


# ═══════════════════════════════════════════════════════════════════════════════




def add_project_agent(state):
    logger.info("Add project agent started")

    user      = state.get("user", {})
    role      = user.get("role")
    hr_emp_id = user.get("emp_id")

    if role != "hr":
        return {"action_status": "Unauthorized: Only HR can add new projects."}

    query        = state["query"]
    chat_history = state.get("chat_history", [])

    # ── Build context: combine last assistant message + current query ──────
    # This lets LLM see "project_id P101, name AL Hatab" even if spread across turns
    history_context = ""
    if chat_history:
        # Grab last few turns to reconstruct partial info from previous messages
        recent = chat_history[-6:]
        history_context = "\n".join(f"{r.upper()}: {c}" for r, c in recent)

    prompt = f"""
You are a project creation extraction agent for an HR system.

Conversation so far:
{history_context if history_context else "None"}

Current message: "{query}"

Extract new project details from the conversation above and return STRICT JSON:
{{
  "project_id": "P005",
  "name": "Project Name",
  "description": "Short description"
}}

Rules:
- Look across ALL messages (history + current) to find the details
- project_id: alphanumeric like P005, PRJ01 — extract exactly as mentioned
- name: project name as stated
- description: if mentioned anywhere in the conversation, include it; else null
- If project_id AND name are both missing/unclear, return null
- Return ONLY JSON, no markdown, no explanation
"""

    raw = llm.invoke(prompt).content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    logger.info(f"Add project LLM output: {raw}")

    # ── LLM returned null or couldn't extract required fields ────────────
    if raw.lower() == "null":
        return {
            # Ask the user for the missing info and signal pending state
            "action_status": (
                "Sure! Please provide the project details:\n"
                "- **Project ID** (e.g. P005)\n"
                "- **Project Name**\n"
                "- **Description** (optional)"
            ),
            "pending_action": "ADD_PROJECT"   # ← signals planner to re-route next turn
        }

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "action_status": (
                "Could not parse project details. "
                "Please provide project ID and project name."
            )
        }

    # ── Check required fields — ask for what's missing ───────────────────
    missing = [f for f in ["project_id", "name"] if not payload.get(f)]
    if missing:
        return {
            "action_status": (
                f"Almost there! Still need: **{', '.join(missing)}**. "
                "Please provide the missing details."
            ),
            "pending_action": "ADD_PROJECT"
        }

    payload["hr_emp_id"] = hr_emp_id
    logger.info(f"Add project payload: {payload}")

    response = requests.post(
        MCP_ADD_PROJECT_URL,
        json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )

    logger.info(f"MCP HTTP status: {response.status_code}")
    logger.info(f"MCP response: {response.text}")

    if response.status_code in (400, 403, 404):
        try:
            msg = response.json().get("error", response.text)
        except Exception:
            msg = response.text or "Project creation failed."
        return {"action_status": msg}

    response.raise_for_status()
    # ── Clear pending_action on success ──────────────────────────────────
    return {
        "action_status":  response.json().get("message", "Project added successfully."),
        "pending_action": None
    }


# ═══════════════════════════════════════════════════════════════════════════════

MCP_ADD_LEAVE_URL = "http://localhost:9000/employee/leave/add"


def add_leave_agent(state):  # ✅ NEW
    logger.info("Add leave agent started")

    user      = state.get("user", {})
    role      = user.get("role")
    hr_emp_id = user.get("emp_id")

    # 🔐 HR-only gate
    if role != "hr":
        return {"action_status": "Unauthorized: Only HR can add leave balances."}

    query        = state["query"]
    chat_history = state.get("chat_history", [])

    # ── Build context from history for multi-turn extraction ─────────────
    history_context = ""
    if chat_history:
        recent = chat_history[-6:]
        history_context = "\n".join(f"{r.upper()}: {c}" for r, c in recent)

    prompt = f"""
You are a leave balance extraction agent for an HR system.

Conversation so far:
{history_context if history_context else "None"}

Current message: "{query}"

Extract leave details from the conversation and return STRICT JSON:
{{
  "emp_id": "E101",
  "balance": 14
}}

Rules:
- emp_id: employee ID like E101, HR001, FN001 — extract exactly as mentioned
- balance: number of leave days (must be a non-negative integer)
- Look across ALL messages (history + current) to find the details
- If emp_id OR balance are missing, return null
- Return ONLY JSON, no markdown, no explanation
"""

    raw = llm.invoke(prompt).content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    logger.info(f"Add leave LLM output: {raw}")

    if raw.lower() == "null":
        return {
            "action_status": (
                "Sure! Please provide the leave details:\n"
                "- **Employee ID** (e.g. E101)\n"
                "- **Leave balance** (number of days)"
            ),
            "pending_action": "ADD_LEAVE"
        }

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "action_status": (
                "Could not parse leave details. "
                "Please say e.g. 'add 14 days leave for E101'"
            )
        }

    missing = [f for f in ["emp_id", "balance"] if payload.get(f) is None or str(payload.get(f, "")).strip() == ""]
    if missing:
        return {
            "action_status": (
                f"Almost there! Still need: **{', '.join(missing)}**. "
                "Please provide the missing details."
            ),
            "pending_action": "ADD_LEAVE"
        }

    payload["hr_emp_id"] = hr_emp_id
    logger.info(f"Add leave payload: {payload}")

    response = requests.post(
        MCP_ADD_LEAVE_URL,
        json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )

    logger.info(f"MCP HTTP status: {response.status_code}")
    logger.info(f"MCP response: {response.text}")

    if response.status_code in (400, 403, 404):
        try:
            msg = response.json().get("error", response.text)
        except Exception:
            msg = response.text or "Failed to add leave balance."
        return {"action_status": msg}

    response.raise_for_status()
    return {
        "action_status":  response.json().get("message", "Leave balance added successfully."),
        "pending_action": None
    }
