# from flask import Blueprint, request, jsonify, abort
# import sqlite3
# from datetime import datetime, timedelta
# import pandas as pd
# import os

# from mcp_server.auth import require_token

# from utils.emailer import send_leave_email

# leave_bp = Blueprint("leave", __name__)

# DB_PATH = "db/hr.db"
# CSV_PATH = "data/leave_log.csv"


# @leave_bp.route("/apply", methods=["POST"])
# def apply_leave():
#     require_token()

#     data = request.json
#     emp_id = data.get("emp_id")
#     days = data.get("days")
#     start_date = data.get("start_date")

#     if not emp_id or not days or not start_date:
#         abort(400, "Missing required fields")

#     start_dt = datetime.fromisoformat(start_date)
#     end_dt = start_dt + timedelta(days=days - 1)

#     conn = sqlite3.connect(DB_PATH)
#     cursor = conn.cursor()

#     # 1️⃣ Fetch current balance
#     cursor.execute(
#         "SELECT balance FROM leaves WHERE emp_id = ?",
#         (emp_id,)
#     )
#     row = cursor.fetchone()

#     if not row:
#         conn.close()
#         abort(404, "Employee not found")

#     total_before = row[0]

#     # 2️⃣ Validate balance
#     if total_before < days:
#         conn.close()
#         abort(400, "Insufficient leave balance")

#     total_after = total_before - days
#     created_at = datetime.utcnow().isoformat()

#     # 3️⃣ Update leaves table
#     cursor.execute(
#         "UPDATE leaves SET balance = ? WHERE emp_id = ?",
#         (total_after, emp_id)
#     )

#     # 4️⃣ Insert into leave_log
#     cursor.execute(
#         """
#         INSERT INTO leave_log (
#             emp_id,
#             created_at,
#             total_leaves_before,
#             leaves_requested,
#             start_date,
#             end_date,
#             total_leaves_after
#         )
#         VALUES (?, ?, ?, ?, ?, ?, ?)
#         """,
#         (
#             emp_id,
#             created_at,
#             total_before,
#             days,
#             start_dt.date().isoformat(),
#             end_dt.date().isoformat(),
#             total_after
#         )
#     )

#     conn.commit()

#     # 5️⃣ Persist leave_log to CSV
#     df = pd.read_sql("SELECT * FROM leave_log", conn)
#     os.makedirs("data", exist_ok=True)
#     df.to_csv(CSV_PATH, index=False)

#     conn.close()

#     return jsonify({
#         "message": "Leave applied successfully",
#         "remaining_balance": total_after
#     })

from flask import Blueprint, request, jsonify, abort
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import os

from mcp_server.auth import require_token
from utils.emailer import send_leave_email
from utils.logger import get_logger
from services.jira_service import create_leave_issue, approve_leave_issue, reject_leave_issue

print("ACTIVE FILE:", __file__)

logger = get_logger("mcp_leave")

leave_bp = Blueprint("leave", __name__)

DB_PATH = "db/hr.db"
CSV_PATH = "data/leave_log.csv"


@leave_bp.route("/apply", methods=["POST"])
def apply_leave():
    issue_key = None   # ✅ DEFINE HERE (outside DB try block)
    
    require_token()

    data = request.json
    emp_id = data.get("emp_id")
    days = data.get("days")
    start_date = data.get("start_date")
    print("NEW APPLY LEAVE LOGIC RUNNING")

    if not emp_id or not days or not start_date:
        abort(400, "Missing required fields")

    start_dt = datetime.fromisoformat(start_date)
    end_dt = start_dt + timedelta(days=days - 1)


    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 1️⃣ Fetch employee details
        cursor.execute(
            "SELECT name, email FROM employees WHERE emp_id = ?",
            (emp_id,)
        )
        emp = cursor.fetchone()

        if not emp:
            abort(404, "Employee not found")

        emp_name, emp_email = emp

        # 2️⃣ Fetch current leave balance
        cursor.execute(
            "SELECT balance FROM leaves WHERE emp_id = ?",
            (emp_id,)
        )
        row = cursor.fetchone()

        if not row:
            abort(404, "Leave record not found")

        total_before = row[0]

        # 3️⃣ Validate balance
        if total_before < days:
            abort(400, "Insufficient leave balance")

        # 4️⃣ Block duplicate dates ← ADD THIS BLOCK
        cursor.execute(
            """
            SELECT id FROM leave_log 
            WHERE emp_id = ? 
            AND status IN ('PENDING_HR', 'APPROVED')
            AND (start_date <= ? AND end_date >= ?)
            """,
            (emp_id, end_dt.date().isoformat(), start_dt.date().isoformat())
        )
        if cursor.fetchone():
            abort(400, "You already have a leave applied for this date range.")

        created_at = datetime.utcnow().isoformat()

        # 8️⃣ Create Jira issue (NON-BLOCKING)
        try:
            jira_resp = create_leave_issue(
                emp_id=emp_id,
                start_date=start_dt.date().isoformat(),
                end_date=end_dt.date().isoformat(),
                days=days
            )
            issue_key = jira_resp.get("key")
        except Exception:
            logger.exception("Failed to create Jira issue")

        # 5️⃣ Insert into leave_log
        cursor.execute(
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            emp_id,
            created_at,
            total_before,
            days,
            start_dt.date().isoformat(),
            end_dt.date().isoformat(),
            "PENDING_HR",
            issue_key 
        )
    )

        conn.commit()

        # 6️⃣ Persist leave_log to CSV
        df = pd.read_sql("SELECT * FROM leave_log", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(CSV_PATH, index=False)

    finally:
        conn.close()

    # 7️⃣ Send confirmation email (NON-BLOCKING)
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
            body=email_body
        )

    except Exception:
        logger.exception("Failed to send leave confirmation email")

    return jsonify({
        "message": f"Leave request submitted for HR approval. Jira issue: {issue_key}"
        if issue_key else
        "Leave request submitted (Jira failed)"
    })

# @leave_bp.route("/approve", methods=["POST"])
# def approve_leave():
#     require_token()

#     data = request.json
#     emp_id = data.get("emp_id")
#     hr_emp_id = data.get("hr_emp_id")

#     if not emp_id:
#         abort(400, "Missing emp_id")

#     conn = sqlite3.connect(DB_PATH)
#     cursor = conn.cursor()

#     try:
#         # Fetch latest pending leave for this employee
#         cursor.execute(
#             "SELECT leaves_requested, jira_issue_key, status FROM leave_log WHERE emp_id = ? AND status = 'PENDING_HR' ORDER BY created_at DESC LIMIT 1",
#             (emp_id,)
#         )
#         row = cursor.fetchone()

#         if not row:
#             abort(404, f"No pending leave found for {emp_id}")

#         days, jira_key, current_status = row

#         # Get balance before deduction
#         cursor.execute("SELECT balance FROM leaves WHERE emp_id = ?", (emp_id,))
#         bal_row = cursor.fetchone()
#         total_after = bal_row[0] - days if bal_row else None

#         # 1. Deduct balance
#         cursor.execute(
#             "UPDATE leaves SET balance = balance - ? WHERE emp_id = ?",
#             (days, emp_id)
#         )

#         # 2. Update leave_log
#         cursor.execute(
#             "UPDATE leave_log SET status = 'APPROVED', total_leaves_after = ? WHERE emp_id = ? AND status = 'PENDING_HR'",
#             (total_after, emp_id)
#         )

#         conn.commit()

#         # 3. Sync CSV
#         df = pd.read_sql("SELECT * FROM leave_log", conn)
#         os.makedirs("data", exist_ok=True)
#         df.to_csv(CSV_PATH, index=False)

#         # 4. Transition Jira
#         if jira_key:
#             try:
#                 approve_leave_issue(jira_key)
#             except Exception:
#                 logger.exception(f"Jira transition failed for {jira_key}")

#     finally:
#         conn.close()

#     return jsonify({"message": f"Leave approved for {emp_id}. Balance updated."})
@leave_bp.route("/approve", methods=["POST"])
def approve_leave():
    require_token()

    data = request.json
    emp_id = data.get("emp_id")
    hr_emp_id = data.get("hr_emp_id")
    filter_days = data.get("days")          # ← NEW: filter by number of days
    filter_start = data.get("start_date")   # ← NEW: filter by start date

    if not emp_id:
        abort(400, "Missing emp_id")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Build dynamic query based on available filters
        query = "SELECT leaves_requested, jira_issue_key, start_date, end_date FROM leave_log WHERE emp_id = ? AND status = 'PENDING_HR'"
        params = [emp_id]

        if filter_days:
            query += " AND leaves_requested = ?"
            params.append(int(filter_days))

        if filter_start:
            query += " AND start_date = ?"
            params.append(filter_start)

        query += " ORDER BY created_at DESC LIMIT 1"

        cursor.execute(query, params)
        row = cursor.fetchone()

        if not row:
            abort(404, f"No matching pending leave found for {emp_id}")

        days, jira_key, start_date, end_date = row

        # Get employee details for email
        cursor.execute("SELECT name, email FROM employees WHERE emp_id = ?", (emp_id,))
        emp = cursor.fetchone()
        emp_name, emp_email = emp if emp else (emp_id, None)

        # Get current balance
        cursor.execute("SELECT balance FROM leaves WHERE emp_id = ?", (emp_id,))
        bal_row = cursor.fetchone()
        current_balance = int(bal_row[0]) if bal_row else 0
        total_after = current_balance - int(days)

        if total_after < 0:
            abort(400, f"Insufficient balance for {emp_id}")

        logger.info(f"Approving leave for {emp_id}: {current_balance} - {days} = {total_after}")

        cursor.execute("UPDATE leaves SET balance = ? WHERE emp_id = ?", (total_after, emp_id))
        cursor.execute(
            "UPDATE leave_log SET status = 'APPROVED', total_leaves_after = ? WHERE emp_id = ? AND status = 'PENDING_HR' AND start_date = ?",
            (total_after, emp_id, start_date)
        )

        conn.commit()

        df = pd.read_sql("SELECT * FROM leave_log", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(CSV_PATH, index=False)

        if jira_key:
            try:
                approve_leave_issue(jira_key)
            except Exception:
                logger.exception(f"Jira transition failed for {jira_key}")

    finally:
        conn.close()

    # 7️⃣ Send approval email (NON-BLOCKING)
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
            body=approval_email_body
        )

    except Exception:
        logger.exception("Failed to send approval email")

    return jsonify({"message": f"Leave approved for {emp_id} ({days} days, {start_date} to {end_date}). Remaining balance: {total_after}."})

@leave_bp.route("/reject", methods=["POST"])
def reject_leave():
    require_token()

    data = request.json
    emp_id = data.get("emp_id")
    hr_emp_id = data.get("hr_emp_id")
    filter_days = data.get("days")
    filter_start = data.get("start_date")

    if not emp_id:
        abort(400, "Missing emp_id")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Fetch matching pending leave
        query = "SELECT leaves_requested, jira_issue_key, start_date, end_date FROM leave_log WHERE emp_id = ? AND status = 'PENDING_HR'"
        params = [emp_id]

        if filter_days:
            query += " AND leaves_requested = ?"
            params.append(int(filter_days))

        if filter_start:
            query += " AND start_date = ?"
            params.append(filter_start)

        query += " ORDER BY created_at DESC LIMIT 1"
        cursor.execute(query, params)
        row = cursor.fetchone()

        if not row:
            abort(404, f"No pending leave found for {emp_id}")

        days, jira_key, start_date, end_date = row

        # Get employee details for email
        cursor.execute("SELECT name, email FROM employees WHERE emp_id = ?", (emp_id,))
        emp = cursor.fetchone()
        emp_name, emp_email = emp if emp else (emp_id, None)

        # Update status to REJECTED (no balance deduction)
        cursor.execute(
            "UPDATE leave_log SET status = 'REJECTED' WHERE emp_id = ? AND status = 'PENDING_HR' AND start_date = ?",
            (emp_id, start_date)
        )

        conn.commit()

        # Sync CSV
        df = pd.read_sql("SELECT * FROM leave_log", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(CSV_PATH, index=False)

        # Transition Jira to Rejected (non-blocking)
        if jira_key:
            try:
                reject_leave_issue(jira_key,)
            except Exception:
                logger.exception(f"Jira rejection failed for {jira_key}")

    finally:
        conn.close()

    # 7️⃣ Send rejection email (NON-BLOCKING)
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
            body=rejection_email_body
        )

    except Exception:
        logger.exception("Failed to send rejection email")

    return jsonify({"message": f"Leave rejected for {emp_id} ({start_date} to {end_date})."})