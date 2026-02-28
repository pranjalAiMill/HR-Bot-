from flask import Blueprint, request, jsonify
from datetime import datetime
import pandas as pd
import os
from sqlalchemy import text

from mcp_server.auth import require_token
from utils.logger import get_logger
from utils.db_loader import get_engine
from services.jira_service import (
    create_service_request_issue,
    approve_service_request_issue,
    reject_service_request_issue,
)

logger = get_logger("mcp_service_request")

service_request_bp = Blueprint("service_request", __name__)

CSV_PATH = "data/service_request_log.csv"
VALID_CATEGORIES = {"software", "hardware", "asset", "access", "other"}
ENGINE = get_engine()


def err(message: str, code: int):
    return jsonify({"success": False, "error": message}), code


def _sync_csv():
    df = pd.read_sql("SELECT * FROM service_request_log", ENGINE)
    os.makedirs("data", exist_ok=True)
    df.to_csv(CSV_PATH, index=False)


@service_request_bp.route("/submit", methods=["POST"])
def submit_service_request():
    require_token()

    data = request.json or {}
    emp_id = data.get("emp_id")
    category = (data.get("category") or "").lower().strip()
    item = (data.get("item") or "").strip()
    reason = (data.get("reason") or "").strip()

    if not emp_id:
        return err("Missing required field: emp_id", 400)
    if not category:
        return err("Missing required field: category", 400)
    if category not in VALID_CATEGORIES:
        return err(
            f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}",
            400,
        )
    if not item:
        return err("Missing required field: item", 400)
    if not reason:
        return err("Missing required field: reason", 400)

    created_at = datetime.utcnow().isoformat()

    with ENGINE.begin() as conn:
        emp = conn.execute(
            text("SELECT name, email FROM employees WHERE emp_id = :emp_id"),
            {"emp_id": emp_id},
        ).fetchone()
        if not emp:
            return err(f"Employee '{emp_id}' not found.", 404)
        emp_name, _ = emp

        duplicate = conn.execute(
            text(
                """
                SELECT id FROM service_request_log
                WHERE emp_id = :emp_id AND item = :item AND status = 'PENDING_HR'
                """
            ),
            {"emp_id": emp_id, "item": item},
        ).fetchone()
        if duplicate:
            return err(
                f"You already have a pending request for '{item}'. "
                "Please wait for HR to process it before submitting again.",
                400,
            )

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

        conn.execute(
            text(
                """
                INSERT INTO service_request_log
                    (emp_id, category, item, reason, status, jira_issue_key, created_at, updated_at)
                VALUES
                    (:emp_id, :category, :item, :reason, 'PENDING_HR', :jira_issue_key, :created_at, :updated_at)
                """
            ),
            {
                "emp_id": emp_id,
                "category": category,
                "item": item,
                "reason": reason,
                "jira_issue_key": jira_key,
                "created_at": created_at,
                "updated_at": created_at,
            },
        )

    _sync_csv()
    logger.info(f"Service request submitted: {emp_id} | {category} | {item}")

    return jsonify(
        {
            "success": True,
            "message": f"Service request for '{item}' submitted successfully. Jira: {jira_key or 'N/A'}",
            "emp_id": emp_id,
            "category": category,
            "item": item,
            "reason": reason,
            "jira_issue": jira_key or "N/A",
            "status": "PENDING_HR",
        }
    )


@service_request_bp.route("/approve", methods=["POST"])
def approve_service_request():
    require_token()

    data = request.json or {}
    emp_id = data.get("emp_id")
    hr_emp_id = data.get("hr_emp_id")
    item = data.get("item")

    if not emp_id:
        return err("Missing required field: emp_id", 400)
    if not hr_emp_id:
        return err("Missing required field: hr_emp_id", 400)

    approved_at = datetime.utcnow().isoformat()

    with ENGINE.begin() as conn:
        if item:
            row = conn.execute(
                text(
                    """
                    SELECT id, item, category, jira_issue_key
                    FROM service_request_log
                    WHERE emp_id = :emp_id AND status = 'PENDING_HR' AND item LIKE :item_pattern
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"emp_id": emp_id, "item_pattern": f"%{item}%"},
            ).fetchone()
        else:
            row = conn.execute(
                text(
                    """
                    SELECT id, item, category, jira_issue_key
                    FROM service_request_log
                    WHERE emp_id = :emp_id AND status = 'PENDING_HR'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"emp_id": emp_id},
            ).fetchone()

        if not row:
            approved_count = conn.execute(
                text("SELECT COUNT(*) FROM service_request_log WHERE emp_id = :emp_id AND status = 'APPROVED'"),
                {"emp_id": emp_id},
            ).scalar() or 0
            if approved_count > 0:
                return (
                    jsonify(
                        {
                            "success": False,
                            "description": f"No pending service requests found for {emp_id}. They may already be approved.",
                        }
                    ),
                    200,
                )
            return err(f"No pending service requests found for {emp_id}.", 404)

        req_id, req_item, req_category, jira_key = row

        conn.execute(
            text(
                """
                UPDATE service_request_log
                SET status = 'APPROVED', updated_at = :updated_at
                WHERE id = :req_id
                """
            ),
            {"updated_at": approved_at, "req_id": req_id},
        )

    _sync_csv()

    if jira_key:
        try:
            approve_service_request_issue(jira_key)
        except Exception:
            logger.exception(f"Failed to transition Jira issue {jira_key}")

    logger.info(f"Service request approved: {emp_id} | {req_item} | by {hr_emp_id}")
    return jsonify(
        {
            "success": True,
            "message": f"Service request for '{req_item}' ({req_category}) approved for {emp_id}.",
        }
    )


@service_request_bp.route("/reject", methods=["POST"])
def reject_service_request():
    require_token()

    data = request.json or {}
    emp_id = data.get("emp_id")
    hr_emp_id = data.get("hr_emp_id")
    rejection_reason = (data.get("rejection_reason") or "").strip()
    item = data.get("item")

    if not emp_id:
        return err("Missing required field: emp_id", 400)
    if not hr_emp_id:
        return err("Missing required field: hr_emp_id", 400)

    rejected_at = datetime.utcnow().isoformat()

    with ENGINE.begin() as conn:
        if item:
            row = conn.execute(
                text(
                    """
                    SELECT id, item, category, jira_issue_key
                    FROM service_request_log
                    WHERE emp_id = :emp_id AND status = 'PENDING_HR' AND item LIKE :item_pattern
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"emp_id": emp_id, "item_pattern": f"%{item}%"},
            ).fetchone()
        else:
            row = conn.execute(
                text(
                    """
                    SELECT id, item, category, jira_issue_key
                    FROM service_request_log
                    WHERE emp_id = :emp_id AND status = 'PENDING_HR'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"emp_id": emp_id},
            ).fetchone()

        if not row:
            return err(f"No pending service requests found for {emp_id}.", 404)

        req_id, req_item, req_category, jira_key = row

        conn.execute(
            text(
                """
                UPDATE service_request_log
                SET status = 'REJECTED', updated_at = :updated_at
                WHERE id = :req_id
                """
            ),
            {"updated_at": rejected_at, "req_id": req_id},
        )

    _sync_csv()

    if jira_key:
        try:
            reject_service_request_issue(jira_key, rejection_reason)
        except Exception:
            logger.exception(f"Failed to reject Jira issue {jira_key}")

    logger.info(f"Service request rejected: {emp_id} | {req_item} | by {hr_emp_id}")
    return jsonify(
        {
            "success": True,
            "message": f"Service request for '{req_item}' ({req_category}) rejected for {emp_id}.",
        }
    )
