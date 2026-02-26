import json
import os
import requests
from datetime import datetime, timezone

from config.llm_factory import get_llm
from utils.logger import get_logger

logger = get_logger("incident")
llm    = get_llm()

MCP_REPORT_URL = os.getenv("MCP_INCIDENT_REPORT_URL", "http://localhost:9000/incident/report")

INCIDENT_TYPES = {
    "IT":         "Server, network, software, security breach",
    "HR":         "Workplace conflict, misconduct, policy violation",
    "FACILITIES": "Power outage, AC failure, infrastructure damage, fire safety",
    "SAFETY":     "Physical injury, hazard, near-miss",
    "FINANCE":    "Fraud, billing error, data discrepancy",
    "COMPLIANCE": "Legal, regulatory, or audit issue",
    "OTHERS":     "Anything that does not fit the above categories"
}

SEVERITIES = ["Low", "Medium", "High", "Critical"]

# Phrases that are just triggers — no actual incident info
VAGUE_TRIGGERS = [
    "report an incident",
    "report incident",
    "log an incident",
    "log incident",
    "raise an incident",
    "raise incident",
    "i want to report",
    "i need to report",
    "file an incident",
    "filing an incident",
    "report an incident for me",
]


def _is_vague(query: str) -> bool:
    """
    Returns True if the query is just a trigger phrase with no actual
    incident details — meaning the employee hasn't described what happened yet.
    """
    q = query.lower().strip()

    # If the query matches a vague trigger almost exactly (within a few words)
    for trigger in VAGUE_TRIGGERS:
        if q == trigger or q.startswith(trigger) and len(q) - len(trigger) < 8:
            return True

    # Also vague if the whole query is under 8 words with no descriptive content
    words = q.split()
    if len(words) <= 8:
        descriptive_words = [
            w for w in words
            if w not in {
                "report", "an", "incident", "for", "me", "i", "want",
                "to", "log", "raise", "file", "a", "please", "need"
            }
        ]
        if len(descriptive_words) == 0:
            return True

    return False


def incident_agent(state):
    logger.info("Incident agent started")

    user   = state.get("user", {})
    emp_id = user.get("emp_id")
    query  = state["query"]

    if not emp_id:
        return {"action_status": "Could not determine your employee ID."}

    # ── Guard: ask for details if no incident was described ───────────────
    if _is_vague(query):
        types_list = "\n".join(f"• **{k}** — {v}" for k, v in INCIDENT_TYPES.items())
        return {
            "action_status": (
                "Sure, I can help you report an incident. Please describe what happened by including:\n\n"
                "1. **What occurred** — brief description of the incident\n"
                "2. **When it occurred** — date and time (if known)\n"
                "3. **Type of incident** — choose one below:\n\n"
                f"{types_list}\n\n"
                "4. **Severity** — Low / Medium / High / Critical\n\n"
                "Example: *\"There was a server outage in production today at 9am, "
                "it caused downtime for 2 hours. IT incident, High severity.\"\n*"
            )
        }

    # ── Proceed with extraction ───────────────────────────────────────────
    now_iso    = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    types_text = "\n".join(f'  "{k}" → {v}' for k, v in INCIDENT_TYPES.items())

    prompt = f"""
You are an incident extraction agent for an HR/IT system.

Current UTC time: {now_iso}

User query: "{query}"

Extract the incident details and return STRICT JSON:
{{
  "title": "Short, clear title of the incident",
  "description": "Full description of what happened",
  "incident_type": "ONE of the type codes below",
  "severity": "Low | Medium | High | Critical",
  "occurred_at": "YYYY-MM-DDTHH:MM:SSZ or null if not mentioned"
}}

Available incident_type codes:
{types_text}

Severity guide:
- Low      → Minor issue, no business impact
- Medium   → Some disruption, workaround available
- High     → Significant impact, no easy workaround
- Critical → Complete outage, safety risk, or major data breach

Rules:
- title must be concise (under 15 words)
- If incident_type is ambiguous, use "OTHERS"
- If severity is not mentioned, infer from description
- If occurred_at is not mentioned, return null
- Return ONLY JSON, no markdown, no explanation
"""

    raw = llm.invoke(prompt).content
    if isinstance(raw, list):
        raw = " ".join(p if isinstance(p, str) else p.get("text", "") for p in raw)
    raw = raw.strip().replace("```json", "").replace("```", "").strip()

    logger.info(f"Incident LLM output: {raw}")

    try:
        details = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse incident LLM output: {raw}")
        return {
            "action_status": (
                "I couldn't fully understand the incident details. "
                "Please describe what happened, the type (IT / HR / Facilities / "
                "Safety / Finance / Compliance / Others), and severity (Low / Medium / High / Critical)."
            )
        }

    # ── Validate extracted fields ─────────────────────────────────────────
    title         = details.get("title", "").strip()
    description   = details.get("description", "").strip()
    incident_type = details.get("incident_type", "OTHERS").upper().strip()
    severity      = details.get("severity", "Medium").strip()
    occurred_at   = details.get("occurred_at")

    if not title or not description:
        return {
            "action_status": (
                "Please provide more detail — what happened and a brief title for the incident."
            )
        }

    if incident_type not in INCIDENT_TYPES:
        incident_type = "OTHERS"

    if severity not in SEVERITIES:
        severity = "Medium"

    payload = {
        "reported_by":   emp_id,
        "title":         title,
        "description":   description,
        "incident_type": incident_type,
        "severity":      severity,
        "occurred_at":   occurred_at
    }

    logger.info(f"Incident report payload: {payload}")

    response = requests.post(
        MCP_REPORT_URL,
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
    return {"action_status": response.json().get("message", "Incident reported successfully.")}