from flask import Blueprint, request, jsonify
import sqlite3
from datetime import datetime
import pandas as pd
import os

from mcp_server.auth import require_token
from utils.logger import get_logger
from services.jira_service import (
    create_service_request_issue,
    approve_service_request_issue,
    reject_service_request_issue
)

logger = get_logger("mcp_service_request")

service_request_bp = Blueprint("service_request", __name__)

DB_PATH  = "db/hr.db"
CSV_PATH = "data/service_request_log.csv"

VALID_CATEGORIES = {"software", "hardware", "asset", "access", "other"}


def err(message: str, code: int):
    return jsonify({"success": False, "error": message}), code


# ──────────────────────────────────────────────
# POST /service-request/submit
# ──────────────────────────────────────────────
@service_request_bp.route("/submit", methods=["POST"])
def submit_service_request():
    require_token()

    data     = request.json or {}
    emp_id   = data.get("emp_id")
    category = (data.get("category") or "").lower().strip()
    item     = (data.get("item") or "").strip()
    reason   = (data.get("reason") or "").strip()

    if not emp_id:
        return err("Missing required field: emp_id", 400)
    if not category:
        return err("Missing required field: category", 400)
    if category not in VALID_CATEGORIES:
        return err(f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}", 400)
    if not item:
        return err("Missing required field: item", 400)
    if not reason:
        return err("Missing required field: reason", 400)

    created_at = datetime.utcnow().isoformat()

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT name, email FROM employees WHERE emp_id = ?", (emp_id,))
        emp = cursor.fetchone()
        if not emp:
            return err(f"Employee '{emp_id}' not found.", 404)
        emp_name, emp_email = emp

        # Block duplicate pending requests for same item
        cursor.execute(
            "SELECT id FROM service_request_log WHERE emp_id = ? AND item = ? AND status = 'PENDING_HR'",
            (emp_id, item)
        )
        if cursor.fetchone():
            return err(
                f"You already have a pending request for '{item}'. "
                "Please wait for HR to process it before submitting again.", 400
            )

        # Create Jira ticket (non-blocking)
        jira_key = None
        try:
            jira_resp = create_service_request_issue(
                emp_id=emp_id,
                emp_name=emp_name,
                category=category,
                item=item,
                reason=reason,
            )
            jira_key = jira_resp.get("key")
            logger.info(f"Jira ticket created: {jira_key}")
        except Exception:
            logger.exception("Failed to create Jira issue for service request")

        cursor.execute(
            """
            INSERT INTO service_request_log
                (emp_id, category, item, reason, status, jira_issue_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'PENDING_HR', ?, ?, ?)
            """,
            (emp_id, category, item, reason, jira_key, created_at, created_at)
        )
        conn.commit()

        df = pd.read_sql("SELECT * FROM service_request_log", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(CSV_PATH, index=False)

        logger.info(f"Service request submitted: {emp_id} | {category} | {item}")

    finally:
        conn.close()

    return jsonify({
        "success":    True,
        "message":    f"Service request for '{item}' submitted successfully. Jira: {jira_key or 'N/A'}",
        "emp_id":     emp_id,
        "category":   category,
        "item":       item,
        "reason":     reason,
        "jira_issue": jira_key or "N/A",
        "status":     "PENDING_HR",
    })


# ──────────────────────────────────────────────
# POST /service-request/approve
# ──────────────────────────────────────────────
@service_request_bp.route("/approve", methods=["POST"])
def approve_service_request():
    require_token()

    data      = request.json or {}
    emp_id    = data.get("emp_id")
    hr_emp_id = data.get("hr_emp_id")
    item      = data.get("item")

    if not emp_id:
        return err("Missing required field: emp_id", 400)
    if not hr_emp_id:
        return err("Missing required field: hr_emp_id", 400)

    approved_at = datetime.utcnow().isoformat()

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        query = "SELECT id, item, category, jira_issue_key FROM service_request_log WHERE emp_id = ? AND status = 'PENDING_HR' AND item LIKE ?"
        params = [emp_id, f"%{item}%"]
        query += " ORDER BY created_at DESC LIMIT 1"

        cursor.execute(query, params)
        row = cursor.fetchone()

        if not row:
            cursor.execute(
                "SELECT COUNT(*) FROM service_request_log WHERE emp_id = ? AND status = 'APPROVED'",
                (emp_id,)
            )
            if cursor.fetchone()[0] > 0:
                return jsonify({
                    "success": False,
                    "description": f"No pending service requests found for {emp_id}. They may already be approved."
                }), 200
            return err(f"No pending service requests found for {emp_id}.", 404)

        req_id, req_item, req_category, jira_key = row

        cursor.execute(
            "UPDATE service_request_log SET status = 'APPROVED', updated_at = ? WHERE id = ?",
            (approved_at, req_id)
        )
        conn.commit()

        df = pd.read_sql("SELECT * FROM service_request_log", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(CSV_PATH, index=False)

        if jira_key:
            try:
                approve_service_request_issue(jira_key)
            except Exception:
                logger.exception(f"Failed to transition Jira issue {jira_key}")

        logger.info(f"Service request approved: {emp_id} | {req_item} | by {hr_emp_id}")

    finally:
        conn.close()

    return jsonify({
        "success": True,
        "message": f"Service request for '{req_item}' ({req_category}) approved for {emp_id}.",
    })


# ──────────────────────────────────────────────
# POST /service-request/reject
# ──────────────────────────────────────────────
@service_request_bp.route("/reject", methods=["POST"])
def reject_service_request():
    require_token()

    data             = request.json or {}
    emp_id           = data.get("emp_id")
    hr_emp_id        = data.get("hr_emp_id")
    rejection_reason = (data.get("rejection_reason") or "").strip()
    item             = data.get("item")

    if not emp_id:
        return err("Missing required field: emp_id", 400)
    if not hr_emp_id:
        return err("Missing required field: hr_emp_id", 400)

    rejected_at = datetime.utcnow().isoformat()

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        query  = "SELECT id, item, category, jira_issue_key FROM service_request_log WHERE emp_id = ? AND status = 'PENDING_HR'"
        params = [emp_id]
        if item:
            query  += " AND item LIKE ?"
            params.append(f"%{item}%")
        query += " ORDER BY created_at DESC LIMIT 1"

        cursor.execute(query, params)
        row = cursor.fetchone()

        if not row:
            return err(f"No pending service requests found for {emp_id}.", 404)

        req_id, req_item, req_category, jira_key = row

        cursor.execute(
            "UPDATE service_request_log SET status = 'REJECTED', updated_at = ? WHERE id = ?",
            (rejected_at, req_id)
        )
        conn.commit()

        df = pd.read_sql("SELECT * FROM service_request_log", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(CSV_PATH, index=False)

        if jira_key:
            try:
                reject_service_request_issue(jira_key, rejection_reason)
            except Exception:
                logger.exception(f"Failed to reject Jira issue {jira_key}")

        logger.info(f"Service request rejected: {emp_id} | {req_item} | by {hr_emp_id}")

    finally:
        conn.close()

    return jsonify({
        "success": True,
        "message": f"Service request for '{req_item}' ({req_category}) rejected for {emp_id}.",
    })