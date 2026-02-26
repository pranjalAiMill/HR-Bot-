import os, re, requests
from datetime import date, timedelta
from utils.logger import get_logger

logger = get_logger("approve")

MCP_LEAVE_APPROVE_URL     = os.getenv("MCP_LEAVE_APPROVE_URL", "http://localhost:9000/leave/approve")
MCP_TIMESHEET_APPROVE_URL = os.getenv("MCP_TIMESHEET_APPROVE_URL", "http://localhost:9000/timesheet/approve")
MCP_SR_APPROVE_URL        = os.getenv("MCP_SR_APPROVE_URL", "http://localhost:9000/service-request/approve")


def get_week_start(d: date) -> str:
    return (d - timedelta(days=d.weekday())).isoformat()


def extract_item(query: str) -> str | None:
    """
    Extract item name from queries like:
    - "approve the laptop service request of E107"
    - "approve headphone request for E107"
    - "approve Gemini API key access for E107"
    """
    patterns = [
        # "approve the ITEM service request of/for EXXX"
        r"approve\s+(?:the\s+)?(.+?)\s+service\s+request\s+(?:of|for)\s+E\d+",
        # "approve ITEM request for EXXX"
        r"approve\s+(?:the\s+)?(.+?)\s+request\s+(?:of|for)\s+E\d+",
        # "approve ITEM for EXXX"
        r"approve\s+(?:the\s+)?(.+?)\s+(?:of|for)\s+E\d+",
    ]

    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            item = match.group(1).strip()
            # Filter out generic words that aren't items
            if item.lower() not in {"leave", "timesheet", "the", "a", "an", "request"}:
                logger.info(f"Extracted item: {item}")
                return item

    return None


def approve_agent(state):
    logger.info("Approve agent started")

    user      = state.get("user", {})
    role      = user.get("role")
    hr_emp_id = user.get("emp_id")

    if role != "hr":
        return {"action_status": "Unauthorized: Only HR can approve requests."}

    query = state["query"]
    q     = query.lower()

    # Extract emp_id via regex
    match = re.search(r'\bE\d{3,}\b', query, re.IGNORECASE)
    if not match:
        return {"action_status": "Could not find employee ID. Please say 'approve leave for E107'."}
    emp_id = match.group(0).upper()
    logger.info(f"emp_id extracted: {emp_id}")

    # ── Route to correct MCP endpoint ────────────────────────────────────────

    if "timesheet" in q:
        today      = date.today()
        week_start = get_week_start(today - timedelta(days=7) if "last week" in q else today)
        logger.info(f"Approving timesheet week: {week_start}")
        url     = MCP_TIMESHEET_APPROVE_URL
        payload = {"emp_id": emp_id, "week_start": week_start, "hr_emp_id": hr_emp_id}

    elif "leave" in q:
        logger.info("Approving leave")
        url     = MCP_LEAVE_APPROVE_URL
        payload = {"emp_id": emp_id, "hr_emp_id": hr_emp_id}

    else:
        # Service Request — extract item so correct request is approved
        item = extract_item(query)
        logger.info(f"Approving service request | item={item}")
        url     = MCP_SR_APPROVE_URL
        payload = {
            "emp_id":    emp_id,
            "hr_emp_id": hr_emp_id,
            "item":      item  # ← passes item to MCP so correct request is approved
        }

    logger.info(f"Calling MCP approve at {url} with payload: {payload}")

    response = requests.post(
        url,
        json=payload,
        headers={"X-MCP-TOKEN": os.getenv("MCP_TOKEN")}
    )

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
    return {"action_status": response.json().get("message", "Approved successfully.")}