from flask import Blueprint, request, jsonify, abort
from datetime import datetime, timedelta
import pandas as pd
import os
from sqlalchemy import text

from mcp_server.auth import require_token
from utils.emailer import send_leave_email
from utils.logger import get_logger
from utils.db_loader import get_engine
from services.jira_service import create_leave_issue, approve_leave_issue, reject_leave_issue

logger = get_logger("mcp_leave")

leave_bp = Blueprint("leave", __name__)

CSV_PATH = "data/leave_log.csv"
ENGINE = get_engine()


def _sync_leave_csv():
    df = pd.read_sql("SELECT * FROM leave_log", ENGINE)
    os.makedirs("data", exist_ok=True)
    df.to_csv(CSV_PATH, index=False)


@leave_bp.route("/apply", methods=["POST"])
def apply_leave():
    issue_key = None

    require_token()

    data = request.json or {}
    emp_id = data.get("emp_id")
    days = data.get("days")
    start_date = data.get("start_date")

    if not emp_id or not days or not start_date:
        abort(400, "Missing required fields")

    start_dt = datetime.fromisoformat(start_date)
    end_dt = start_dt + timedelta(days=int(days) - 1)

    with ENGINE.begin() as conn:
        emp = conn.execute(
            text("SELECT name, email FROM employees WHERE emp_id = :emp_id"),
            {"emp_id": emp_id},
        ).fetchone()

        if not emp:
            abort(404, "Employee not found")

        emp_name, emp_email = emp

        row = conn.execute(
            text("SELECT balance FROM leaves WHERE emp_id = :emp_id"),
            {"emp_id": emp_id},
        ).fetchone()

        if not row:
            abort(404, "Leave record not found")

        total_before = int(row[0])

        if total_before < int(days):
            abort(400, "Insufficient leave balance")

        duplicate = conn.execute(
            text(
                """
                SELECT id FROM leave_log
                WHERE emp_id = :emp_id
                  AND status IN ('PENDING_HR', 'APPROVED')
                  AND (start_date <= :end_date AND end_date >= :start_date)
                """
            ),
            {
                "emp_id": emp_id,
                "end_date": end_dt.date().isoformat(),
                "start_date": start_dt.date().isoformat(),
            },
        ).fetchone()
        if duplicate:
            abort(400, "You already have a leave applied for this date range.")

        created_at = datetime.utcnow().isoformat()

        try:
            jira_resp = create_leave_issue(
                emp_id=emp_id,
                start_date=start_dt.date().isoformat(),
                end_date=end_dt.date().isoformat(),
                days=int(days),
            )
            issue_key = jira_resp.get("key")
        except Exception:
            logger.exception("Failed to create Jira issue")

        conn.execute(
            text(
                """
                INSERT INTO leave_log (
                    emp_id,
                    created_at,
                    total_leaves_before,
                    leaves_requested,
                    start_date,
                    end_date,
                    status,
                    jira_issue_key
                )
                VALUES (
                    :emp_id,
                    :created_at,
                    :total_before,
                    :days,
                    :start_date,
                    :end_date,
                    :status,
                    :jira_issue_key
                )
                """
            ),
            {
                "emp_id": emp_id,
                "created_at": created_at,
                "total_before": total_before,
                "days": int(days),
                "start_date": start_dt.date().isoformat(),
                "end_date": end_dt.date().isoformat(),
                "status": "PENDING_HR",
                "jira_issue_key": issue_key,
            },
        )

    _sync_leave_csv()

    try:
        email_body = f"""
Hi {emp_name},

Your leave request has been submitted for HR approval:

Start Date: {start_dt.date().isoformat()}
End Date: {end_dt.date().isoformat()}
Days Requested: {days}
Jira Issue: {issue_key or 'Not created'}

Your request is now pending HR approval.

HR Bot
""".strip()

        send_leave_email(
            to_email=emp_email,
            subject="Leave Request Submitted",
            body=email_body,
        )

    except Exception:
        logger.exception("Failed to send leave confirmation email")

    return jsonify(
        {
            "message": (
                f"Leave request submitted for HR approval. Jira issue: {issue_key}"
                if issue_key
                else "Leave request submitted (Jira failed)"
            )
        }
    )


@leave_bp.route("/approve", methods=["POST"])
def approve_leave():
    require_token()

    data = request.json or {}
    emp_id = data.get("emp_id")
    filter_days = data.get("days")
    filter_start = data.get("start_date")

    if not emp_id:
        abort(400, "Missing emp_id")

    with ENGINE.begin() as conn:
        query = (
            "SELECT leaves_requested, jira_issue_key, start_date, end_date "
            "FROM leave_log WHERE emp_id = :emp_id AND status = 'PENDING_HR'"
        )
        params = {"emp_id": emp_id}

        if filter_days:
            query += " AND leaves_requested = :filter_days"
            params["filter_days"] = int(filter_days)

        if filter_start:
            query += " AND start_date = :filter_start"
            params["filter_start"] = filter_start

        query += " ORDER BY created_at DESC LIMIT 1"

        row = conn.execute(text(query), params).fetchone()

        if not row:
            abort(404, f"No matching pending leave found for {emp_id}")

        days, jira_key, start_date, end_date = row

        emp = conn.execute(
            text("SELECT name, email FROM employees WHERE emp_id = :emp_id"),
            {"emp_id": emp_id},
        ).fetchone()
        emp_name, emp_email = emp if emp else (emp_id, None)

        bal_row = conn.execute(
            text("SELECT balance FROM leaves WHERE emp_id = :emp_id"),
            {"emp_id": emp_id},
        ).fetchone()
        current_balance = int(bal_row[0]) if bal_row else 0
        total_after = current_balance - int(days)

        if total_after < 0:
            abort(400, f"Insufficient balance for {emp_id}")

        logger.info(f"Approving leave for {emp_id}: {current_balance} - {days} = {total_after}")

        conn.execute(
            text("UPDATE leaves SET balance = :balance WHERE emp_id = :emp_id"),
            {"balance": total_after, "emp_id": emp_id},
        )
        conn.execute(
            text(
                """
                UPDATE leave_log
                SET status = 'APPROVED', total_leaves_after = :total_after
                WHERE emp_id = :emp_id AND status = 'PENDING_HR' AND start_date = :start_date
                """
            ),
            {"total_after": total_after, "emp_id": emp_id, "start_date": start_date},
        )

    _sync_leave_csv()

    if jira_key:
        try:
            approve_leave_issue(jira_key)
        except Exception:
            logger.exception(f"Jira transition failed for {jira_key}")

    try:
        approval_email_body = f"""
Hi {emp_name},

Your leave request has been APPROVED by HR:

Start Date: {start_date}
End Date: {end_date}
Days Approved: {days}
Remaining Balance: {total_after} days
Jira Issue: {jira_key or 'N/A'}

Your leave is now confirmed. Please update your calendar accordingly.

HR Bot
""".strip()

        send_leave_email(
            to_email=emp_email,
            subject="Leave Request APPROVED",
            body=approval_email_body,
        )

    except Exception:
        logger.exception("Failed to send approval email")

    return jsonify(
        {
            "message": (
                f"Leave approved for {emp_id} ({days} days, {start_date} to {end_date}). "
                f"Remaining balance: {total_after}."
            )
        }
    )


@leave_bp.route("/reject", methods=["POST"])
def reject_leave():
    require_token()

    data = request.json or {}
    emp_id = data.get("emp_id")
    filter_days = data.get("days")
    filter_start = data.get("start_date")

    if not emp_id:
        abort(400, "Missing emp_id")

    with ENGINE.begin() as conn:
        query = (
            "SELECT leaves_requested, jira_issue_key, start_date, end_date "
            "FROM leave_log WHERE emp_id = :emp_id AND status = 'PENDING_HR'"
        )
        params = {"emp_id": emp_id}

        if filter_days:
            query += " AND leaves_requested = :filter_days"
            params["filter_days"] = int(filter_days)

        if filter_start:
            query += " AND start_date = :filter_start"
            params["filter_start"] = filter_start

        query += " ORDER BY created_at DESC LIMIT 1"
        row = conn.execute(text(query), params).fetchone()

        if not row:
            abort(404, f"No pending leave found for {emp_id}")

        days, jira_key, start_date, end_date = row

        emp = conn.execute(
            text("SELECT name, email FROM employees WHERE emp_id = :emp_id"),
            {"emp_id": emp_id},
        ).fetchone()
        emp_name, emp_email = emp if emp else (emp_id, None)

        conn.execute(
            text(
                """
                UPDATE leave_log
                SET status = 'REJECTED'
                WHERE emp_id = :emp_id AND status = 'PENDING_HR' AND start_date = :start_date
                """
            ),
            {"emp_id": emp_id, "start_date": start_date},
        )

    _sync_leave_csv()

    if jira_key:
        try:
            reject_leave_issue(jira_key)
        except Exception:
            logger.exception(f"Jira rejection failed for {jira_key}")

    try:
        rejection_email_body = f"""
Hi {emp_name},

Your leave request has been REJECTED by HR:

Start Date: {start_date}
End Date: {end_date}
Days Requested: {days}
Jira Issue: {jira_key or 'N/A'}

Please contact HR for more details about this decision.

HR Bot
""".strip()

        send_leave_email(
            to_email=emp_email,
            subject="Leave Request REJECTED",
            body=rejection_email_body,
        )

    except Exception:
        logger.exception("Failed to send rejection email")

    return jsonify(
        {
            "message": (
                f"Leave rejected for {emp_id} ({days} days, {start_date} to {end_date})."
            )
        }
    )
