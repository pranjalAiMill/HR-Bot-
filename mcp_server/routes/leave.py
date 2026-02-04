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

logger = get_logger("mcp_leave")

leave_bp = Blueprint("leave", __name__)

DB_PATH = "db/hr.db"
CSV_PATH = "data/leave_log.csv"


@leave_bp.route("/apply", methods=["POST"])
def apply_leave():
    require_token()

    data = request.json
    emp_id = data.get("emp_id")
    days = data.get("days")
    start_date = data.get("start_date")

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

        total_after = total_before - days
        created_at = datetime.utcnow().isoformat()

        # 4️⃣ Update leaves table
        cursor.execute(
            "UPDATE leaves SET balance = ? WHERE emp_id = ?",
            (total_after, emp_id)
        )

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
                total_leaves_after
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                emp_id,
                created_at,
                total_before,
                days,
                start_dt.date().isoformat(),
                end_dt.date().isoformat(),
                total_after
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

As per your request, your leave has been marked for approval.

Leave Period:
From: {start_dt.date().isoformat()}
To:   {end_dt.date().isoformat()}
Total Days: {days}

Regards,
HR Bot
""".strip()

        send_leave_email(
            to_email=emp_email,
            subject="Leave Request Submitted",
            body=email_body
        )

    except Exception:
        # ❗ Email failure must NOT break the API
        logger.exception("Failed to send leave confirmation email")

    return jsonify({
        "message": "Leave applied successfully",
        "remaining_balance": total_after
    })
