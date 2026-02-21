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