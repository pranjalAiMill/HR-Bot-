import json
from pathlib import Path

SCHEMA_PATH = Path("config/schema.json")


def load_schema() -> dict:
    if not SCHEMA_PATH.exists():
        raise RuntimeError(f"Schema file not found: {SCHEMA_PATH}")

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_schema_prompt() -> str:
    schema = load_schema()

    lines = ["Database schema:\n"]

    for table, meta in schema.items():
        lines.append(f"Table: {table}")
        lines.append(f"Description: {meta.get('description', '')}")
        lines.append("Columns:")

        for col, desc in meta.get("columns", {}).items():
            lines.append(f"  - {col}: {desc}")

        lines.append("")

    return "\n".join(lines)
