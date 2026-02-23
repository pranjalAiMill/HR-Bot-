from flask import Blueprint, request, jsonify
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import os

from mcp_server.auth import require_token
from utils.logger import get_logger
from services.jira_service import create_timesheet_issue, add_jira_comment
from services.jira_service import approve_timesheet_issue

logger = get_logger("mcp_timesheet")

timesheet_bp = Blueprint("timesheet", __name__)

DB_PATH  = "db/hr.db"
CSV_PATH = "data/timesheet_log.csv"


def get_week_window(date_str: str):
    d = datetime.fromisoformat(date_str).date()
    week_start = d - timedelta(days=d.weekday())
    week_end   = week_start + timedelta(days=6)
    return week_start.isoformat(), week_end.isoformat()


def err(message: str, code: int):
    return jsonify({"success": False, "description": message}), code


@timesheet_bp.route("/submit", methods=["POST"])
def submit_timesheet():
    require_token()

    data       = request.json or {}
    emp_id     = data.get("emp_id")
    date_str   = data.get("date")
    hours      = data.get("hours")
    project_id = data.get("project_id")

    if not emp_id:
        return err("Missing required field: emp_id", 400)
    if not date_str:
        return err("Missing required field: date", 400)
    if not hours:
        return err("Missing required field: hours", 400)
    if not project_id:
        return err("Missing required field: project_id", 400)

    try:
        datetime.fromisoformat(date_str)
    except ValueError:
        return err(f"Invalid date format: '{date_str}'. Use YYYY-MM-DD.", 400)

    if not isinstance(hours, (int, float)) or hours <= 0 or hours > 24:
        return err("hours must be a number between 1 and 24.", 400)

    week_start, week_end = get_week_window(date_str)
    created_at    = datetime.utcnow().isoformat()
    already_existed = False

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT name FROM employees WHERE emp_id = ?", (emp_id,))
        emp = cursor.fetchone()
        if not emp:
            return err(f"Employee '{emp_id}' not found. Please check the employee ID.", 404)

        cursor.execute("SELECT name FROM projects WHERE project_id = ?", (project_id,))
        proj = cursor.fetchone()
        if not proj:
            return err(f"Project '{project_id}' does not exist.", 404)
        project_name = proj[0]

        cursor.execute(
            "SELECT hours_per_week FROM project_allocations WHERE emp_id = ? AND project_id = ?",
            (emp_id, project_id)
        )
        alloc = cursor.fetchone()
        if not alloc:
            return err(
                f"{emp_id} is not allocated to project '{project_name}' ({project_id}). "
                f"You can only log hours for projects assigned to you.", 403
            )

        hours_per_week = alloc[0]

        cursor.execute(
            """
            SELECT COUNT(*) FROM leave_log
            WHERE emp_id = ?
              AND status = 'APPROVED'
              AND start_date <= ?
              AND end_date >= ?
            """,
            (emp_id, week_end, week_start)
        )
        leave_days   = cursor.fetchone()[0]
        working_days = max(1, 5 - leave_days)
        daily_limit  = round(hours_per_week / working_days, 2)

        if hours > daily_limit:
            return err(
                f"Cannot log {hours} hours for '{project_name}'. "
                f"Your daily limit is {daily_limit} hrs "
                f"({hours_per_week} hrs/week / {working_days} working days "
                f"— {leave_days} approved leave day(s) this week).", 400
            )

        # ✅ Check if entry already exists for same emp + project + date
        cursor.execute(
            "SELECT id, jira_issue_key FROM timesheet_log WHERE emp_id = ? AND project_id = ? AND date = ?",
            (emp_id, project_id, date_str)
        )
        existing = cursor.fetchone()

        if existing:
            # ── OVERWRITE existing entry ──
            existing_id, jira_key = existing
            already_existed = True

            cursor.execute(
                "UPDATE timesheet_log SET hours = ?, updated_at = ?, week_start = ?, week_end = ? WHERE id = ?",
                (hours, created_at, week_start, week_end, existing_id)
            )
            conn.commit()
            logger.info(f"Timesheet UPDATED for {emp_id} | {date_str} | {project_id} | {hours}h")

            if jira_key:
                try:
                    add_jira_comment(
                        jira_key,
                        f"Timesheet updated by {emp_id} on {created_at[:10]}.\n"
                        f"Date: {date_str} | Hours: {hours} | Project: {project_name}"
                    )
                except Exception:
                    logger.exception(f"Failed to update Jira comment for {jira_key}")

        else:
            # ── Check if Jira ticket already exists for this emp + project + week ──
            cursor.execute(
                """
                SELECT jira_issue_key FROM timesheet_log
                WHERE emp_id = ? AND project_id = ? AND week_start = ?
                  AND jira_issue_key IS NOT NULL
                LIMIT 1
                """,
                (emp_id, project_id, week_start)
            )
            existing_ticket = cursor.fetchone()
            jira_key = existing_ticket[0] if existing_ticket else None

            if not jira_key:
                try:
                    jira_resp = create_timesheet_issue(
                        emp_id=emp_id, date=date_str, hours=hours,
                        project=project_name, week_start=week_start, week_end=week_end
                    )
                    jira_key = jira_resp.get("key")
                    logger.info(f"Jira ticket created: {jira_key}")
                except Exception:
                    logger.exception("Failed to create Jira ticket — continuing")
            else:
                try:
                    add_jira_comment(
                        jira_key,
                        f"New entry by {emp_id} on {created_at[:10]}.\n"
                        f"Date: {date_str} | Hours: {hours} | Project: {project_name}"
                    )
                except Exception:
                    logger.exception(f"Failed to add Jira comment to {jira_key}")

            cursor.execute(
                """
                INSERT INTO timesheet_log (
                    emp_id, project_id, date, hours,
                    week_start, week_end, status, jira_issue_key,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    emp_id, project_id, date_str, hours,
                    week_start, week_end, "PENDING_HR", jira_key,
                    created_at, created_at
                )
            )
            conn.commit()
            logger.info(f"Timesheet INSERTED for {emp_id} | {date_str} | {project_id} | {hours}h")

        df = pd.read_sql("SELECT * FROM timesheet_log", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(CSV_PATH, index=False)

    finally:
        conn.close()

    # ✅ Clear message depending on whether it was new or existing
    if already_existed:
        message = (
            f"A timesheet for {date_str} on {project_name} already existed — "
            f"it has been updated to {hours} hours. Jira: {jira_key or 'N/A'}"
        )
    else:
        message = f"Timesheet submitted successfully. Jira: {jira_key or 'N/A'}"

    return jsonify({
        "success":      True,
        "message":      message,
        "emp_id":       emp_id,
        "project":      project_name,
        "date":         date_str,
        "hours":        hours,
        "daily_limit":  daily_limit,
        "week":         f"{week_start} to {week_end}",
        "jira_issue":   jira_key or "N/A",
        "already_existed": already_existed
    })


@timesheet_bp.route("/approve", methods=["POST"])
def approve_timesheet_week():
    require_token()

    data       = request.json or {}
    emp_id     = data.get("emp_id")
    week_start = data.get("week_start")
    hr_emp_id  = data.get("hr_emp_id")

    if not emp_id:
        return err("Missing required field: emp_id", 400)
    if not week_start:
        return err("Missing required field: week_start", 400)
    if not hr_emp_id:
        return err("Missing required field: hr_emp_id", 400)

    approved_at = datetime.utcnow().isoformat()
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT jira_issue_key FROM timesheet_log
            WHERE emp_id = ? AND week_start = ? AND status = 'PENDING_HR'
            """,
            (emp_id, week_start)
        )
        jira_rows = cursor.fetchall()
        count     = len(jira_rows)

        if count == 0:
            # ✅ Check if already approved — inform HR clearly
            cursor.execute(
                "SELECT COUNT(*) FROM timesheet_log WHERE emp_id = ? AND week_start = ? AND status = 'APPROVED'",
                (emp_id, week_start)
            )
            already_approved = cursor.fetchone()[0]

            if already_approved > 0:
                return jsonify({
                    "success":     False,
                    "description": f"Timesheets for {emp_id} for the week of {week_start} are already approved. No action needed."
                }), 200

            return err(
                f"No timesheets found for {emp_id} for the week of {week_start}. "
                f"The employee may not have submitted any entries yet.", 404
            )

        # Update DB
        cursor.execute(
            """
            UPDATE timesheet_log
            SET status = 'APPROVED', approved_by = ?, approved_at = ?
            WHERE emp_id = ? AND week_start = ? AND status = 'PENDING_HR'
            """,
            (hr_emp_id, approved_at, emp_id, week_start)
        )
        conn.commit()

        # Transition Jira issues after commit
        for (jira_key,) in jira_rows:
            if jira_key:
                try:
                    approve_timesheet_issue(jira_key)
                except Exception:
                    logger.exception(f"Failed to transition Jira issue {jira_key}")

        df = pd.read_sql("SELECT * FROM timesheet_log", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(CSV_PATH, index=False)

        logger.info(f"Timesheets approved for {emp_id} week {week_start} by {hr_emp_id}")

    finally:
        conn.close()

    return jsonify({
        "success":     True,
        "message":     f"Approved {count} timesheet entries for {emp_id} (week of {week_start})",
        "approved_by": hr_emp_id,
        "approved_at": approved_at
    })