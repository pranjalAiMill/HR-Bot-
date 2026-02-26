from flask import Blueprint, request, jsonify
import sqlite3
from datetime import datetime
import pandas as pd
import os

from mcp_server.auth import require_token
from utils.logger import get_logger
from services.jira_service import create_incident_issue

logger = get_logger("mcp_incident")

incident_bp = Blueprint("incident", __name__)

DB_PATH  = "db/hr.db"
CSV_PATH = "data/incident_log.csv"


def err(message: str, code: int):
    return jsonify({"success": False, "description": message}), code


def generate_incident_id(cursor) -> str:
    """
    Generates sequential INC-YYYY-NNNN.
    Scans existing IDs for the current year and increments the max.
    """
    year = datetime.utcnow().year
    prefix = f"INC-{year}-"

    cursor.execute(
        "SELECT incident_id FROM incidents WHERE incident_id LIKE ?",
        (f"{prefix}%",)
    )
    rows = cursor.fetchall()

    if not rows:
        return f"{prefix}0001"

    max_seq = max(int(r[0].split("-")[-1]) for r in rows)
    return f"{prefix}{str(max_seq + 1).zfill(4)}"


# ──────────────────────────────────────────────
# POST /incident/report
# ──────────────────────────────────────────────
@incident_bp.route("/report", methods=["POST"])
def report_incident():
    require_token()

    data          = request.json or {}
    emp_id        = data.get("reported_by")
    title         = data.get("title")
    description   = data.get("description")
    incident_type = data.get("incident_type")
    severity      = data.get("severity", "Medium")
    occurred_at   = data.get("occurred_at")       # optional, ISO string

    # ── Validation ────────────────────────────────────────────────────────
    if not emp_id:
        return err("Missing required field: reported_by", 400)
    if not title:
        return err("Missing required field: title", 400)
    if not description:
        return err("Missing required field: description", 400)
    if not incident_type:
        return err("Missing required field: incident_type", 400)

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Verify employee exists
        cursor.execute("SELECT name FROM employees WHERE emp_id = ?", (emp_id,))
        emp = cursor.fetchone()
        if not emp:
            return err(f"Employee '{emp_id}' not found.", 404)

        # Verify incident type is valid
        cursor.execute(
            "SELECT type_id FROM incident_types WHERE type_id = ?",
            (incident_type.upper(),)
        )
        if not cursor.fetchone():
            cursor.execute("SELECT type_id FROM incident_types")
            valid = [r[0] for r in cursor.fetchall()]
            return err(
                f"Invalid incident_type '{incident_type}'. "
                f"Valid types: {', '.join(valid)}", 400
            )

        reported_at = datetime.utcnow().isoformat()
        # Default occurred_at to reported_at if not supplied
        if not occurred_at:
            occurred_at = reported_at

        # Generate sequential incident ID
        incident_id = generate_incident_id(cursor)

        # ── Create Jira ticket ────────────────────────────────────────────
        jira_key = None
        try:
            jira_resp = create_incident_issue(
                incident_id=incident_id,
                emp_id=emp_id,
                emp_name=emp[0],
                title=title,
                description=description,
                incident_type=incident_type,
                severity=severity,
                occurred_at=occurred_at
            )
            jira_key = jira_resp.get("key")
            logger.info(f"Jira ticket created: {jira_key}")
        except Exception:
            logger.exception("Failed to create Jira ticket — incident will still be logged")

        # ── Insert into incidents table ───────────────────────────────────
        cursor.execute(
            """
            INSERT INTO incidents (
                incident_id, title, description, incident_type,
                severity, status, reported_by, reported_at,
                occurred_at, jira_issue_key
            )
            VALUES (?, ?, ?, ?, ?, 'Investigating', ?, ?, ?, ?)
            """,
            (
                incident_id, title, description, incident_type.upper(),
                severity, emp_id, reported_at, occurred_at, jira_key
            )
        )
        conn.commit()

        # ── Persist to CSV ────────────────────────────────────────────────
        df = pd.read_sql("SELECT * FROM incidents", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(CSV_PATH, index=False)

        logger.info(f"Incident {incident_id} reported by {emp_id} | type={incident_type} | severity={severity}")

    finally:
        conn.close()

    return jsonify({
        "success":       True,
        "message":       (
            f"Incident reported successfully. Your incident ID is {incident_id}. "
            f"Jira ticket: {jira_key}."
            if jira_key else
            f"Incident reported successfully. Your incident ID is {incident_id}. "
            f"(Jira ticket creation failed, but the incident is logged.)"
        ),
        "incident_id":   incident_id,
        "title":         title,
        "incident_type": incident_type.upper(),
        "severity":      severity,
        "status":        "Investigating",
        "jira_issue":    jira_key or "N/A",
        "reported_at":   reported_at
    })


# ──────────────────────────────────────────────
# GET /incident/list  — HR sees all, employee sees own
# ──────────────────────────────────────────────
@incident_bp.route("/list", methods=["GET"])
def list_incidents():
    require_token()

    emp_id = request.args.get("emp_id")
    role   = request.args.get("role", "employee")

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        if role == "hr":
            cursor.execute(
                """
                SELECT incident_id, title, incident_type, severity,
                       status, reported_by, reported_at, jira_issue_key
                FROM incidents
                ORDER BY reported_at DESC
                """
            )
        else:
            if not emp_id:
                return err("emp_id required for employee role", 400)
            cursor.execute(
                """
                SELECT incident_id, title, incident_type, severity,
                       status, reported_by, reported_at, jira_issue_key
                FROM incidents
                WHERE reported_by = ?
                ORDER BY reported_at DESC
                """,
                (emp_id,)
            )

        rows = cursor.fetchall()

    finally:
        conn.close()

    results = [
        {
            "incident_id":   r[0],
            "title":         r[1],
            "incident_type": r[2],
            "severity":      r[3],
            "status":        r[4],
            "reported_by":   r[5],
            "reported_at":   r[6],
            "jira_issue_key": r[7]
        }
        for r in rows
    ]

    return jsonify({"success": True, "incidents": results, "count": len(results)})