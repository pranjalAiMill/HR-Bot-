import os
import requests

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "HR")


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

def reject_leave_issue(issue_key: str, reason: str = "Rejected by HR"):
    transition_id = get_transition_id(issue_key, target_status="Won't Do")
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
    payload = {"transition": {"id": transition_id}}
    requests.post(
        url,
        json=payload,
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json"}
    ).raise_for_status()