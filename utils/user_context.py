import json
from pathlib import Path

USER_MAP_PATH = Path("config/user_mapping.json")

def _load_map() -> dict:
    if not USER_MAP_PATH.exists():
        return {}
    with USER_MAP_PATH.open() as f:
        return json.load(f)

def get_user_context(slack_user_id: str) -> dict:
    if not slack_user_id:
        return {}
    return _load_map().get(slack_user_id, {})

def get_user_context_by_any(user_obj: dict) -> dict:
    """Tries ID first, then email. Works for both Slack and OpenWebUI."""
    if not user_obj:
        return {}
    data = _load_map()

    # Try direct ID match
    user_id = user_obj.get("id", "")
    if user_id and user_id in data:
        return data[user_id]

    # Try email match
    email = user_obj.get("email", "").lower()
    if email:
        for ctx in data.values():
            if ctx.get("email", "").lower() == email:
                return ctx

    return {}