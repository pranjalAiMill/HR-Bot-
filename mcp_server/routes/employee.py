from flask import Blueprint, request, jsonify
import sqlite3
import re
import pandas as pd
import os

from mcp_server.auth import require_token
from utils.logger import get_logger

logger = get_logger("mcp_employee")

employee_bp = Blueprint("employee", __name__)

DB_PATH  = "db/hr.db"
CSV_PATH = "data/employees.csv"
PROJECT_CSV_PATH = "data/projects.csv"  # Project.csv
LEAVE_CSV_PATH = "data/leaves.csv"  # Leave.csv

def err(message: str, code: int):
    return jsonify({"success": False, "error": message}), code


@employee_bp.route("/onboard", methods=["POST"])
def onboard_employee():
    require_token()

    data       = request.json or {}
    hr_emp_id  = data.get("hr_emp_id")
    emp_id     = (data.get("emp_id") or "").strip().upper()
    name       = (data.get("name") or "").strip()
    department = (data.get("department") or "").strip()
    email      = (data.get("email") or "").strip()

    # ── Basic field validation ────────────────────────────────────────────
    if not hr_emp_id:
        return err("Missing required field: hr_emp_id", 400)
    if not emp_id:
        return err("Missing required field: emp_id", 400)
    if not re.match(r"^[A-Z0-9]{2,10}$", emp_id):
        return err(
            f"Invalid emp_id format: '{emp_id}'. "
            "Use alphanumeric like E108, HR005, FN004.", 400
        )
    if not name:
        return err("Missing required field: name", 400)
    if not email or "@" not in email:
        return err("Missing or invalid email address.", 400)

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # ── HR auth check — just verify hr_emp_id exists in DB ───────────
        cursor.execute(
            "SELECT emp_id FROM employees WHERE emp_id = ?",
            (hr_emp_id,)
        )
        hr_row = cursor.fetchone()
        if not hr_row:
            return err(f"HR employee '{hr_emp_id}' not found.", 404)

        # ── Fetch valid departments dynamically from DB ───────────────────
        cursor.execute(
            "SELECT DISTINCT department FROM employees WHERE department IS NOT NULL"
        )
        valid_departments = {row[0] for row in cursor.fetchall()}

        # Case-insensitive match
        matched_dept = next(
            (d for d in valid_departments if d.lower() == department.lower()),
            None
        )

        if department and not matched_dept:
            return err(
                f"Unknown department '{department}'. "
                f"Existing departments: {', '.join(sorted(valid_departments))}. "
                f"If this is a new department, ask an admin to add it first.",
                400
            )

        # If no department provided, default to General
        final_department = matched_dept if matched_dept else "General"

        # ── Check emp_id not already taken ───────────────────────────────
        cursor.execute(
            "SELECT emp_id FROM employees WHERE emp_id = ?",
            (emp_id,)
        )
        if cursor.fetchone():
            return err(
                f"Employee ID '{emp_id}' already exists. Please use a different ID.",
                400
            )

        # ── Check email not already taken ────────────────────────────────
        cursor.execute(
            "SELECT emp_id FROM employees WHERE LOWER(email) = LOWER(?)",
            (email,)
        )
        existing_email = cursor.fetchone()
        if existing_email:
            return err(
                f"Email '{email}' is already registered to employee {existing_email[0]}.",
                400
            )

        # ── INSERT ───────────────────────────────────────────────────────
        # ── INSERT ───────────────────────────────────────────────────────
        cursor.execute(
            """
            INSERT INTO employees (emp_id, name, department, email)
            VALUES (?, ?, ?, ?)
            """,
            (emp_id, name, final_department, email)
        )
        conn.commit()

        # ── Sync to CSV (must be BEFORE conn.close()) ─────────────────────
        actual_path = os.path.abspath(CSV_PATH)
        logger.info(f"Writing CSV to: {actual_path}")
        df = pd.read_sql("SELECT * FROM employees", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(CSV_PATH, index=False)

        logger.info(
            f"Employee onboarded | emp_id={emp_id} | name={name} "
            f"| dept={final_department} | by HR={hr_emp_id}"
        )
        logger.info("employees.csv synced")

    finally:
        conn.close()  # ← conn closes AFTER csv sync now

    return jsonify({
        "success":    True,
        "message":    (
            f"Employee {name} ({emp_id}) has been onboarded successfully "
            f"in the {final_department} department."
        ),
        "emp_id":     emp_id,
        "name":       name,
        "department": final_department,
        "email":      email,
    })

@employee_bp.route("/project/add", methods=["POST"])  
def add_project():
    require_token()

    data        = request.json or {}
    hr_emp_id   = data.get("hr_emp_id")
    project_id  = (data.get("project_id") or "").strip().upper()
    name        = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()

    # ── Field validation (same style as onboard_employee) ────────────────
    if not hr_emp_id:
        return err("Missing required field: hr_emp_id", 400)
    if not project_id:
        return err("Missing required field: project_id", 400)
    if not re.match(r"^[A-Z0-9]{2,10}$", project_id):
        return err(
            f"Invalid project_id format: '{project_id}'. "
            "Use alphanumeric like P005, PRJ01.", 400
        )
    if not name:
        return err("Missing required field: name", 400)

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # ── Verify HR employee exists (same check as onboard) ─────────────
        cursor.execute("SELECT emp_id FROM employees WHERE emp_id = ?", (hr_emp_id,))
        if not cursor.fetchone():
            return err(f"HR employee '{hr_emp_id}' not found.", 404)

        # ── Check project_id not already taken ────────────────────────────
        cursor.execute("SELECT project_id FROM projects WHERE project_id = ?", (project_id,))
        if cursor.fetchone():
            return err(
                f"Project ID '{project_id}' already exists. Please use a different ID.", 400
            )

        # ── Check project name not already taken ──────────────────────────
        cursor.execute(
            "SELECT project_id FROM projects WHERE LOWER(name) = LOWER(?)", (name,)
        )
        existing_name = cursor.fetchone()
        if existing_name:
            return err(
                f"A project named '{name}' already exists (ID: {existing_name[0]}).", 400
            )

        # ── INSERT into projects table (mirrors INSERT in onboard) ─────────
        cursor.execute(
            "INSERT INTO projects (project_id, name, description) VALUES (?, ?, ?)",
            (project_id, name, description)
        )
        conn.commit()

        # ── Sync to projects.csv (same pattern as employees.csv sync) ──────
        df = pd.read_sql("SELECT * FROM projects", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(PROJECT_CSV_PATH, index=False)

        logger.info(
            f"Project added | project_id={project_id} | name={name} | by HR={hr_emp_id}"
        )
        logger.info("projects.csv synced")

    finally:
        conn.close()

    return jsonify({
        "success":     True,
        "message":     f"Project '{name}' ({project_id}) has been added successfully.",
        "project_id":  project_id,
        "name":        name,
        "description": description,
    })


    # ═══════════════════════════════════════════════════════════════════════════════



@employee_bp.route("/leave/add", methods=["POST"])  
def add_leave():
    require_token()

    data      = request.json or {}
    hr_emp_id = data.get("hr_emp_id")
    emp_id    = (data.get("emp_id") or "").strip().upper()
    balance   = data.get("balance")

    # ── Field validation ──────────────────────────────────────────────────
    if not hr_emp_id:
        return err("Missing required field: hr_emp_id", 400)
    if not emp_id:
        return err("Missing required field: emp_id", 400)
    if balance is None:
        return err("Missing required field: balance", 400)
    try:
        balance = int(balance)
        if balance < 0:
            raise ValueError()
    except (ValueError, TypeError):
        return err("balance must be a non-negative integer.", 400)

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # ── Verify HR employee exists ─────────────────────────────────────
        cursor.execute("SELECT emp_id FROM employees WHERE emp_id = ?", (hr_emp_id,))
        if not cursor.fetchone():
            return err(f"HR employee '{hr_emp_id}' not found.", 404)

        # ── emp_id must exist in employees (core constraint) ──────────────
        cursor.execute("SELECT emp_id FROM employees WHERE emp_id = ?", (emp_id,))
        if not cursor.fetchone():
            return err(
                f"Employee '{emp_id}' not found in employees table. "
                "Only existing employees can have leave records.", 404
            )

        # ── Insert or update leave balance ────────────────────────────────
        cursor.execute("SELECT balance FROM leaves WHERE emp_id = ?", (emp_id,))
        existing = cursor.fetchone()

        if existing:
            old_balance = existing[0]
            cursor.execute(
                "UPDATE leaves SET balance = ? WHERE emp_id = ?",
                (balance, emp_id)
            )
            action = "updated"
        else:
            cursor.execute(
                "INSERT INTO leaves (emp_id, balance) VALUES (?, ?)",
                (emp_id, balance)
            )
            action = "added"

        conn.commit()

        # ── Sync to leaves.csv ────────────────────────────────────────────
        df = pd.read_sql("SELECT * FROM leaves", conn)
        os.makedirs("data", exist_ok=True)
        df.to_csv(LEAVE_CSV_PATH, index=False)

        logger.info(
            f"Leave balance {action} | emp_id={emp_id} | balance={balance} | by HR={hr_emp_id}"
        )
        logger.info("leaves.csv synced")

    finally:
        conn.close()

    return jsonify({
        "success": True,
        "message": f"Leave balance for {emp_id} has been {action} to {balance} days.",
        "emp_id":  emp_id,
        "balance": balance,
        "action":  action,
    })
