import os
import requests

JIRA_BASE_URL    = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL       = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN   = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "HR")
JIRA_TIMESHEET_PROJECT_KEY = os.getenv("JIRA_TIMESHEET_PROJECT_KEY", "TS")
JIRA_SR_PROJECT_KEY = os.getenv("JIRA_SR_PROJECT_KEY", "SR")
JIRA_INCIDENT_PROJECT_KEY  = os.getenv("JIRA_INCIDENT_PROJECT_KEY", "IR")

def _auth():
    return (JIRA_EMAIL, JIRA_API_TOKEN)

def _headers():
    return {"Accept": "application/json", "Content-Type": "application/json"}

def _make_description(text: str) -> dict:
    return {
        "type": "doc", "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]
    }



def create_leave_issue(emp_id: str, start_date: str, end_date: str, days: int):
    url = f"{JIRA_BASE_URL}/rest/api/3/issue"

    description_text = (
        f"Employee {emp_id} requested {days} day(s) leave.\n"
        f"Start Date: {start_date}\n"
        f"End Date: {end_date}"
    )

    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": f"Leave Request - {emp_id}",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": description_text
                            }
                        ]
                    }
                ]
            },
            "issuetype": {"name": "Task"}
        }
    }

    response = requests.post(
        url,
        json=payload,
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json"}
    )

    response.raise_for_status()
    return response.json()

def get_transition_id(issue_key: str, target_status: str = "Done") -> str:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
    response = requests.get(
        url,
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json"}
    )
    response.raise_for_status()
    transitions = response.json().get("transitions", [])
    for t in transitions:
        if t["to"]["name"].lower() == target_status.lower():
            return t["id"]
    raise RuntimeError(f"Transition to '{target_status}' not found")


def approve_leave_issue(issue_key: str):
    transition_id = get_transition_id(issue_key, target_status="Done")
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
    payload = {"transition": {"id": transition_id}}
    response = requests.post(
        url,
        json=payload,
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json"}
    )
    response.raise_for_status()

def reject_leave_issue(issue_key: str):
    # Transition to Done + add rejection comment
    transition_id = get_transition_id(issue_key, target_status="Done")
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
    requests.post(
        url,
        json={"transition": {"id": transition_id}},
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json"}
    ).raise_for_status()

    # Add comment to distinguish from approvals
    comment_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
    requests.post(
        comment_url,
        json={
            "body": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "❌ REJECTED by HR."}]}]
            }
        },
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json"}
    )

# ──────────────────────────────────────────────
# TIMESHEET
# ──────────────────────────────────────────────
def create_timesheet_issue(emp_id: str, date: str, hours: int, project: str):
    """Creates a Jira issue in the TS (Timesheet) project."""
    url = f"{JIRA_BASE_URL}/rest/api/3/issue"
    payload = {
        "fields": {
            "project":     {"key": JIRA_TIMESHEET_PROJECT_KEY},
            "summary":     f"Timesheet - {emp_id} | {date} | {project}",
            "description": _make_description(
                f"Employee  : {emp_id}\n"
                f"Date      : {date}\n"
                f"Hours     : {hours}\n"
                f"Project   : {project}"
            ),
            "issuetype": {"name": "Task"}
        }
    }
    response = requests.post(url, json=payload, auth=_auth(), headers=_headers())
    response.raise_for_status()
    return response.json()


# ── Updated create_timesheet_issue with week window ──
def create_timesheet_issue(emp_id: str, date: str, hours: int, project: str,
                            week_start: str = None, week_end: str = None):
    """Creates a Jira issue in the TS project for a weekly timesheet."""
    url = f"{JIRA_BASE_URL}/rest/api/3/issue"

    week_info = f"Week: {week_start} to {week_end}\n" if week_start else ""

    payload = {
        "fields": {
            "project":     {"key": JIRA_TIMESHEET_PROJECT_KEY},
            "summary":     f"Timesheet - {emp_id} | {project} | Week of {week_start or date}",
            "description": _make_description(
                f"Employee  : {emp_id}\n"
                f"Project   : {project}\n"
                f"{week_info}"
                f"First Entry: {date} — {hours} hrs"
            ),
            "issuetype": {"name": "Task"}
        }
    }
    response = requests.post(url, json=payload, auth=_auth(), headers=_headers())
    response.raise_for_status()
    return response.json()

def add_jira_comment(issue_key: str, comment_text: str):
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": comment_text}]
                }
            ]
        }
    }
    response = requests.post(url, json=payload, auth=(JIRA_EMAIL, JIRA_API_TOKEN),
                             headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()


def approve_timesheet_issue(issue_key):
    transition_id = get_transition_id(issue_key, target_status="Done")  

    response = requests.post(
        f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions",
        json={"transition": {"id": transition_id}},
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json", "Content-Type": "application/json"}
    )

    response.raise_for_status()


# ──────────────────────────────────────────────
# Service Request
# ──────────────────────────────────────────────

def create_service_request_issue(emp_id: str, emp_name: str, category: str, item: str, reason: str):
    url = f"{JIRA_BASE_URL}/rest/api/3/issue"
    payload = {
        "fields": {
            "project":     {"key": JIRA_SR_PROJECT_KEY},
            "summary":     f"Service Request - {emp_id} | {category.title()} | {item}",
            "description": _make_description(
                f"Employee : {emp_id} ({emp_name})\n"
                f"Category : {category.title()}\n"
                f"Item     : {item}\n"
                f"Reason   : {reason}"
            ),
            "issuetype": {"name": "Task"},
        }
    }
    response = requests.post(url, json=payload, auth=_auth(), headers=_headers())
    response.raise_for_status()
    return response.json()


def approve_service_request_issue(issue_key: str):
    transition_id = get_transition_id(issue_key, target_status="Done")
    requests.post(
        f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions",
        json={"transition": {"id": transition_id}},
        auth=_auth(), headers=_headers()
    ).raise_for_status()


def reject_service_request_issue(issue_key: str, rejection_reason: str = ""):
    transition_id = get_transition_id(issue_key, target_status="Done")
    requests.post(
        f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions",
        json={"transition": {"id": transition_id}},
        auth=_auth(), headers=_headers()
    ).raise_for_status()

    comment_text = "❌ REJECTED by HR."
    if rejection_reason:
        comment_text += f"\nReason: {rejection_reason}"

    requests.post(
        f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment",
        json={
            "body": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment_text}]}]
            }
        },
        auth=_auth(), headers=_headers()
    )

# ──────────────────────────────────────────────
# INCIDENT  — dedicated INC project space
# ──────────────────────────────────────────────

_SEVERITY_TO_JIRA_PRIORITY = {
    "Low":      "Low",
    "Medium":   "Medium",
    "High":     "High",
    "Critical": "Highest"
}

_TYPE_LABEL = {
    "IT":         "[IT]",
    "HR":         "[HR]",
    "FACILITIES": "[Facilities]",
    "SAFETY":     "[Safety]",
    "FINANCE":    "[Finance]",
    "COMPLIANCE": "[Compliance]",
    "OTHERS":     "[Other]",
}


def create_incident_issue(incident_id: str, emp_id: str, emp_name: str,
                           title: str, description: str,
                           incident_type: str, severity: str,
                           occurred_at: str) -> dict:
    """
    Creates a Jira issue in the INCIDENT project space (JIRA_INCIDENT_PROJECT_KEY).
    Completely separate from HR and TS projects.

    Summary format:
        [INC-2026-0001] [IT] Server outage in production
    """
    url = f"{JIRA_BASE_URL}/rest/api/3/issue"

    type_label    = _TYPE_LABEL.get(incident_type.upper(), "[Other]")
    jira_priority = _SEVERITY_TO_JIRA_PRIORITY.get(severity, "Medium")
    summary       = f"[{incident_id}] {type_label} {title}"

    body_text = (
        f"Incident ID   : {incident_id}\n"
        f"Reported By   : {emp_name} ({emp_id})\n"
        f"Type          : {incident_type}\n"
        f"Severity      : {severity}\n"
        f"Occurred At   : {occurred_at}\n\n"
        f"Description:\n{description}"
    )

    payload = {
        "fields": {
            "project":     {"key": JIRA_INCIDENT_PROJECT_KEY},   # ← INC project
            "summary":     summary,
            "description": _make_description(body_text),
            "issuetype":   {"name": "Task"},
            "priority":    {"name": jira_priority},
            "labels":      ["incident", incident_type.lower(), severity.lower()]
        }
    }

    response = requests.post(url, json=payload, auth=_auth(), headers=_headers())
    response.raise_for_status()
    return response.json()