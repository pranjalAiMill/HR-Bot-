from flask import Blueprint, request, jsonify
from datetime import datetime
import pandas as pd
import os
from sqlalchemy import text

from mcp_server.auth import require_token
from utils.logger import get_logger
from utils.db_loader import get_engine
from services.jira_service import create_incident_issue

logger = get_logger("mcp_incident")

incident_bp = Blueprint("incident", __name__)

CSV_PATH = "data/incident_log.csv"
ENGINE = get_engine()


def err(message: str, code: int):
    return jsonify({"success": False, "description": message}), code


def _sync_csv():
    df = pd.read_sql("SELECT * FROM incidents", ENGINE)
    os.makedirs("data", exist_ok=True)
    df.to_csv(CSV_PATH, index=False)


def generate_incident_id(conn) -> str:
    year = datetime.utcnow().year
    prefix = f"INC-{year}-"

    rows = conn.execute(
        text("SELECT incident_id FROM incidents WHERE incident_id LIKE :prefix"),
        {"prefix": f"{prefix}%"},
    ).fetchall()

    if not rows:
        return f"{prefix}0001"

    max_seq = max(int(r[0].split("-")[-1]) for r in rows)
    return f"{prefix}{str(max_seq + 1).zfill(4)}"


@incident_bp.route("/report", methods=["POST"])
def report_incident():
    require_token()

    data = request.json or {}
    emp_id = data.get("reported_by")
    title = data.get("title")
    description = data.get("description")
    incident_type = data.get("incident_type")
    severity = data.get("severity", "Medium")
    occurred_at = data.get("occurred_at")

    if not emp_id:
        return err("Missing required field: reported_by", 400)
    if not title:
        return err("Missing required field: title", 400)
    if not description:
        return err("Missing required field: description", 400)
    if not incident_type:
        return err("Missing required field: incident_type", 400)

    with ENGINE.begin() as conn:
        emp = conn.execute(
            text("SELECT name FROM employees WHERE emp_id = :emp_id"),
            {"emp_id": emp_id},
        ).fetchone()
        if not emp:
            return err(f"Employee '{emp_id}' not found.", 404)

        type_exists = conn.execute(
            text("SELECT type_id FROM incident_types WHERE type_id = :type_id"),
            {"type_id": incident_type.upper()},
        ).fetchone()
        if not type_exists:
            valid = conn.execute(text("SELECT type_id FROM incident_types")).fetchall()
            valid_types = [r[0] for r in valid]
            return err(
                f"Invalid incident_type '{incident_type}'. Valid types: {', '.join(valid_types)}",
                400,
            )

        reported_at = datetime.utcnow().isoformat()
        if not occurred_at:
            occurred_at = reported_at

        incident_id = generate_incident_id(conn)

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
                occurred_at=occurred_at,
            )
            jira_key = jira_resp.get("key")
            logger.info(f"Jira ticket created: {jira_key}")
        except Exception:
            logger.exception("Failed to create Jira ticket - incident will still be logged")

        conn.execute(
            text(
                """
                INSERT INTO incidents (
                    incident_id, title, description, incident_type,
                    severity, status, reported_by, reported_at,
                    occurred_at, jira_issue_key
                )
                VALUES (
                    :incident_id, :title, :description, :incident_type,
                    :severity, 'Investigating', :reported_by, :reported_at,
                    :occurred_at, :jira_issue_key
                )
                """
            ),
            {
                "incident_id": incident_id,
                "title": title,
                "description": description,
                "incident_type": incident_type.upper(),
                "severity": severity,
                "reported_by": emp_id,
                "reported_at": reported_at,
                "occurred_at": occurred_at,
                "jira_issue_key": jira_key,
            },
        )

    _sync_csv()
    logger.info(f"Incident {incident_id} reported by {emp_id} | type={incident_type} | severity={severity}")

    return jsonify(
        {
            "success": True,
            "message": (
                f"Incident reported successfully. Your incident ID is {incident_id}. Jira ticket: {jira_key}."
                if jira_key
                else (
                    f"Incident reported successfully. Your incident ID is {incident_id}. "
                    "(Jira ticket creation failed, but the incident is logged.)"
                )
            ),
            "incident_id": incident_id,
            "title": title,
            "incident_type": incident_type.upper(),
            "severity": severity,
            "status": "Investigating",
            "jira_issue": jira_key or "N/A",
            "reported_at": reported_at,
        }
    )


@incident_bp.route("/list", methods=["GET"])
def list_incidents():
    require_token()

    emp_id = request.args.get("emp_id")
    role = request.args.get("role", "employee")

    with ENGINE.connect() as conn:
        if role == "hr":
            rows = conn.execute(
                text(
                    """
                    SELECT incident_id, title, incident_type, severity,
                           status, reported_by, reported_at, jira_issue_key
                    FROM incidents
                    ORDER BY reported_at DESC
                    """
                )
            ).fetchall()
        else:
            if not emp_id:
                return err("emp_id required for employee role", 400)

            rows = conn.execute(
                text(
                    """
                    SELECT incident_id, title, incident_type, severity,
                           status, reported_by, reported_at, jira_issue_key
                    FROM incidents
                    WHERE reported_by = :emp_id
                    ORDER BY reported_at DESC
                    """
                ),
                {"emp_id": emp_id},
            ).fetchall()

    results = [
        {
            "incident_id": r[0],
            "title": r[1],
            "incident_type": r[2],
            "severity": r[3],
            "status": r[4],
            "reported_by": r[5],
            "reported_at": r[6],
            "jira_issue_key": r[7],
        }
        for r in rows
    ]

    return jsonify({"success": True, "incidents": results, "count": len(results)})
