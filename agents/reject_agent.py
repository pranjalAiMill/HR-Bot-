import json, os, re, requests
from datetime import date
from config.llm_factory import get_llm
from utils.logger import get_logger

logger = get_logger("reject")
llm = get_llm()

MCP_LEAVE_REJECT_URL = os.getenv("MCP_LEAVE_REJECT_URL", "http://localhost:9000/leave/reject")
MCP_SR_REJECT_URL    = os.getenv("MCP_SR_REJECT_URL", "http://localhost:9000/service-request/reject")


def reject_agent(state):
    logger.info("Reject agent started")

    user      = state.get("user", {})
    role      = user.get("role")
    hr_emp_id = user.get("emp_id")
    today     = date.today().isoformat()

    if role != "hr":
        return {"action_status": "Unauthorized: Only HR can reject requests."}

    query = state["query"]
    q     = query.lower()

    # Extract emp_id via regex
    match = re.search(r'\bE\d{3,}\b', query, re.IGNORECASE)
    if not match:
        return {"action_status": "Could not find employee ID. Please say 'reject leave for E107'."}
    emp_id = match.group(0).upper()
    logger.info(f"emp_id extracted: {emp_id}")

    # ── Route: leave vs service request ──────────────────────────────────────

    if "leave" in q:
        # Leave rejection — use LLM to extract optional date filter
        prompt = f"""
Extract rejection details from this HR query.
Today's date is: {today}

Query: "{query}"

Return STRICT JSON with only the fields clearly mentioned:
{{
  "emp_id": "E107",
  "start_date": "2026-03-17"
}}

Rules:
- emp_id: employee ID like E007, E101 (include if mentioned)
- days: ONLY include if explicitly stated as a duration e.g. "2 days", "3 day leave"
- start_date: if a date is mentioned like "17 march" → "{date.today().year}-03-17"
- Numbers that are part of a DATE (like "17" in "17 march") are NOT days
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
            payload["emp_id"] = emp_id  # fallback to regex-extracted

        payload["hr_emp_id"] = hr_emp_id
        url = MCP_LEAVE_REJECT_URL

    else:
        # Service request rejection — extract optional reason
        reason_match = re.search(r"(?:reason[:\s]+|because\s+|as\s+)(.+)", q)
        rejection_reason = reason_match.group(1).strip() if reason_match else ""

        payload = {
            "emp_id":           emp_id,
            "hr_emp_id":        hr_emp_id,
            "rejection_reason": rejection_reason,
        }
        url = MCP_SR_REJECT_URL
        logger.info(f"Rejecting service request: {payload}")

    logger.info(f"Calling MCP reject at {url} with payload: {payload}")

    response = requests.post(
        url,
        json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )

    logger.info(f"MCP HTTP status: {response.status_code}")
    logger.info(f"MCP response body: {response.text}")

    if response.status_code in (400, 404):
        try:
            msg = (
                response.json().get("error")
                or response.json().get("description")
                or response.text
            )
        except Exception:
            msg = response.text or "Request failed."
        return {"action_status": msg}

    response.raise_for_status()
    return {"action_status": response.json().get("message", "Rejected successfully.")}