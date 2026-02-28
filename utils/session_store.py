from datetime import datetime
from sqlalchemy import text

from utils.db_loader import get_engine

MAX_HISTORY = 10  # last 5 turns (10 messages)
ENGINE = get_engine()


def get_history(session_id: str) -> list:
    """Fetch recent chat history for a session."""
    if not session_id:
        return []

    try:
        with ENGINE.connect() as conn:
            rows = conn.execute(text("""
            SELECT role, content FROM chat_history
            WHERE session_id = :session_id
            ORDER BY created_at DESC
            LIMIT :max_history
        """), {"session_id": session_id, "max_history": MAX_HISTORY}).fetchall()
        return list(reversed(rows))  # [(role, content), ...]
    except Exception:
        return []


def save_history(session_id: str, role: str, content: str):
    """Save a single message to chat history."""
    if not session_id:
        return

    with ENGINE.begin() as conn:
        conn.execute(text("""
            INSERT INTO chat_history (session_id, role, content, created_at)
            VALUES (:session_id, :role, :content, :created_at)
        """), {
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": datetime.utcnow().isoformat(),
        })

        # Prune old messages — keep only last MAX_HISTORY per session
        conn.execute(text("""
            DELETE FROM chat_history
            WHERE session_id = :session_id AND id NOT IN (
                SELECT id FROM chat_history
                WHERE session_id = :session_id
                ORDER BY created_at DESC
                LIMIT :max_history
            )
        """), {"session_id": session_id, "max_history": MAX_HISTORY})


def clear_history(session_id: str):
    """Clear all history for a session."""
    with ENGINE.begin() as conn:
        conn.execute(
            text("DELETE FROM chat_history WHERE session_id = :session_id"),
            {"session_id": session_id},
        )
