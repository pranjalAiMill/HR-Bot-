import json
import os
import re
import requests
from datetime import date, datetime, timedelta

from config.llm_factory import get_llm
from utils.logger import get_logger

logger = get_logger("timesheet")
llm    = get_llm()

MCP_SUBMIT_URL  = "http://localhost:9000/timesheet/submit"
MCP_APPROVE_URL = "http://localhost:9000/timesheet/approve"


def get_week_start(d: date) -> str:
    return (d - timedelta(days=d.weekday())).isoformat()


def timesheet_agent(state):
    logger.info("Timesheet agent started")

    user     = state.get("user", {})
    emp_id   = user.get("emp_id")
    role     = user.get("role", "employee")
    query    = state["query"]
    q        = query.lower()

    if not emp_id:
        return {"action_status": "Could not determine your employee ID."}

    today = date.today().isoformat()

    # ── HR approving a weekly timesheet ──
    if role == "hr" and "approve" in q and "timesheet" in q:
        # Extract emp_id via regex
        match = re.search(r'\bE\d{3,}\b', query, re.IGNORECASE)
        target_emp = match.group(0).upper() if match else None

        if not target_emp:
            return {"action_status": "Please mention the employee ID to approve. E.g. 'approve timesheet for E007 this week'"}

        # Extract week — default to current week
        week_start = get_week_start(date.today())

        payload = {
            "emp_id":     target_emp,
            "week_start": week_start,
            "hr_emp_id":  emp_id
        }
        logger.info(f"Timesheet approval payload: {payload}")

        response = requests.post(
            MCP_APPROVE_URL,
            json=payload,
            headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
        )
        response.raise_for_status()
        return {"action_status": response.json().get("message", "Timesheet approved.")}

    # ── Employee submitting timesheet ──
    prompt = f"""
You are a timesheet extraction agent.
Today's date is: {today}

User query: "{query}"

Extract timesheet details and return STRICT JSON:
{{
  "date": "YYYY-MM-DD",
  "hours": 4,
  "project_id": "P001"
}}

Available project IDs:
- P001 = AI Automation
- P002 = HR Portal
- P003 = Payroll System
- P004 = Recruitment Drive

Rules:
- Resolve relative dates: "today" → {today}, "yesterday" → previous date
- hours must be a number between 1 and 24
- Match project name to correct project_id
- If project not mentioned, return project_id as null
- No markdown, no explanation, ONLY JSON
"""

    raw = llm.invoke(prompt).content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    logger.info(f"Timesheet LLM output: {raw}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"action_status": "Could not parse timesheet. Please say: 'submit timesheet for today, 4 hours on AI Automation'"}

    if not payload.get("project_id"):
        return {"action_status": "Please mention which project to log hours for. E.g. 'submit timesheet for today, 4 hours on AI Automation'"}

    # Resolve date
    d = payload.get("date", today)
    try:
        datetime.fromisoformat(d)
    except ValueError:
        d = today
    payload["date"]   = d
    payload["emp_id"] = emp_id  # always from trusted context

    logger.info(f"Timesheet submit payload: {payload}")

    response = requests.post(
        MCP_SUBMIT_URL,
        json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )

    if response.status_code in (400, 403, 404):
        try:
            msg = response.json().get("description", response.text)
        except Exception:
            msg = response.text or "Request rejected."
        return {"action_status": msg}

    response.raise_for_status()
    return {"action_status": response.json().get("message", "Timesheet submitted successfully.")}