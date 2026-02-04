import json
from pathlib import Path

USER_MAP_PATH = Path("config/user_mapping.json")

def get_user_context(slack_user_id: str) -> dict:
    if not slack_user_id or not USER_MAP_PATH.exists():
        return {}

    with USER_MAP_PATH.open() as f:
        data = json.load(f)

    return data.get(slack_user_id, {})
