import sqlite3
from datetime import datetime

DB_PATH = "db/hr.db"
MAX_HISTORY = 10  # last 5 turns (10 messages)


def get_history(session_id: str) -> list:
    """Fetch recent chat history for a session."""
    if not session_id:
        return []

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content FROM chat_history
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (session_id, MAX_HISTORY))
        rows = cursor.fetchall()
        return list(reversed(rows))  # [(role, content), ...]
    except Exception:
        return []
    finally:
        conn.close()


def save_history(session_id: str, role: str, content: str):
    """Save a single message to chat history."""
    if not session_id:
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT INTO chat_history (session_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
        """, (session_id, role, content, datetime.utcnow().isoformat()))
        conn.commit()

        # Prune old messages — keep only last MAX_HISTORY per session
        conn.execute("""
            DELETE FROM chat_history
            WHERE session_id = ? AND id NOT IN (
                SELECT id FROM chat_history
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            )
        """, (session_id, session_id, MAX_HISTORY))
        conn.commit()
    finally:
        conn.close()


def clear_history(session_id: str):
    """Clear all history for a session."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()