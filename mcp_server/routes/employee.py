from flask import Blueprint, request, jsonify
import re
import pandas as pd
import os
from sqlalchemy import text

from mcp_server.auth import require_token
from utils.logger import get_logger
from utils.db_loader import get_engine

logger = get_logger("mcp_employee")

employee_bp = Blueprint("employee", __name__)

CSV_PATH = "data/employees.csv"
PROJECT_CSV_PATH = "data/projects.csv"
LEAVE_CSV_PATH = "data/leaves.csv"
ENGINE = get_engine()


def err(message: str, code: int):
    return jsonify({"success": False, "error": message}), code


@employee_bp.route("/onboard", methods=["POST"])
def onboard_employee():
    require_token()

    data = request.json or {}
    hr_emp_id = data.get("hr_emp_id")
    emp_id = (data.get("emp_id") or "").strip().upper()
    name = (data.get("name") or "").strip()
    department = (data.get("department") or "").strip()
    email = (data.get("email") or "").strip()

    if not hr_emp_id:
        return err("Missing required field: hr_emp_id", 400)
    if not emp_id:
        return err("Missing required field: emp_id", 400)
    if not re.match(r"^[A-Z0-9]{2,10}$", emp_id):
        return err(
            f"Invalid emp_id format: '{emp_id}'. Use alphanumeric like E108, HR005, FN004.",
            400,
        )
    if not name:
        return err("Missing required field: name", 400)
    if not email or "@" not in email:
        return err("Missing or invalid email address.", 400)

    with ENGINE.begin() as conn:
        hr_row = conn.execute(
            text("SELECT emp_id FROM employees WHERE emp_id = :hr_emp_id"),
            {"hr_emp_id": hr_emp_id},
        ).fetchone()
        if not hr_row:
            return err(f"HR employee '{hr_emp_id}' not found.", 404)

        dept_rows = conn.execute(
            text("SELECT DISTINCT department FROM employees WHERE department IS NOT NULL")
        ).fetchall()
        valid_departments = {row[0] for row in dept_rows if row[0]}

        matched_dept = next((d for d in valid_departments if d.lower() == department.lower()), None)

        if department and not matched_dept:
            return err(
                f"Unknown department '{department}'. Existing departments: {', '.join(sorted(valid_departments))}. "
                "If this is a new department, ask an admin to add it first.",
                400,
            )

        final_department = matched_dept if matched_dept else "General"

        existing_emp = conn.execute(
            text("SELECT emp_id FROM employees WHERE emp_id = :emp_id"),
            {"emp_id": emp_id},
        ).fetchone()
        if existing_emp:
            return err(f"Employee ID '{emp_id}' already exists. Please use a different ID.", 400)

        existing_email = conn.execute(
            text("SELECT emp_id FROM employees WHERE LOWER(email) = LOWER(:email)"),
            {"email": email},
        ).fetchone()
        if existing_email:
            return err(f"Email '{email}' is already registered to employee {existing_email[0]}.", 400)

        conn.execute(
            text(
                """
                INSERT INTO employees (emp_id, name, department, email)
                VALUES (:emp_id, :name, :department, :email)
                """
            ),
            {"emp_id": emp_id, "name": name, "department": final_department, "email": email},
        )

    actual_path = os.path.abspath(CSV_PATH)
    logger.info(f"Writing CSV to: {actual_path}")
    df = pd.read_sql("SELECT * FROM employees", ENGINE)
    os.makedirs("data", exist_ok=True)
    df.to_csv(CSV_PATH, index=False)

    logger.info(
        f"Employee onboarded | emp_id={emp_id} | name={name} | dept={final_department} | by HR={hr_emp_id}"
    )
    logger.info("employees.csv synced")

    return jsonify(
        {
            "success": True,
            "message": f"Employee {name} ({emp_id}) has been onboarded successfully in the {final_department} department.",
            "emp_id": emp_id,
            "name": name,
            "department": final_department,
            "email": email,
        }
    )


@employee_bp.route("/project/add", methods=["POST"])
def add_project():
    require_token()

    data = request.json or {}
    hr_emp_id = data.get("hr_emp_id")
    project_id = (data.get("project_id") or "").strip().upper()
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()

    if not hr_emp_id:
        return err("Missing required field: hr_emp_id", 400)
    if not project_id:
        return err("Missing required field: project_id", 400)
    if not re.match(r"^[A-Z0-9]{2,10}$", project_id):
        return err(f"Invalid project_id format: '{project_id}'. Use alphanumeric like P005, PRJ01.", 400)
    if not name:
        return err("Missing required field: name", 400)

    with ENGINE.begin() as conn:
        hr_row = conn.execute(
            text("SELECT emp_id FROM employees WHERE emp_id = :hr_emp_id"),
            {"hr_emp_id": hr_emp_id},
        ).fetchone()
        if not hr_row:
            return err(f"HR employee '{hr_emp_id}' not found.", 404)

        existing_project = conn.execute(
            text("SELECT project_id FROM projects WHERE project_id = :project_id"),
            {"project_id": project_id},
        ).fetchone()
        if existing_project:
            return err(f"Project ID '{project_id}' already exists. Please use a different ID.", 400)

        existing_name = conn.execute(
            text("SELECT project_id FROM projects WHERE LOWER(name) = LOWER(:name)"),
            {"name": name},
        ).fetchone()
        if existing_name:
            return err(f"A project named '{name}' already exists (ID: {existing_name[0]}).", 400)

        conn.execute(
            text("INSERT INTO projects (project_id, name, description) VALUES (:project_id, :name, :description)"),
            {"project_id": project_id, "name": name, "description": description},
        )

    df = pd.read_sql("SELECT * FROM projects", ENGINE)
    os.makedirs("data", exist_ok=True)
    df.to_csv(PROJECT_CSV_PATH, index=False)

    logger.info(f"Project added | project_id={project_id} | name={name} | by HR={hr_emp_id}")
    logger.info("projects.csv synced")

    return jsonify(
        {
            "success": True,
            "message": f"Project '{name}' ({project_id}) has been added successfully.",
            "project_id": project_id,
            "name": name,
            "description": description,
        }
    )


@employee_bp.route("/leave/add", methods=["POST"])
def add_leave():
    require_token()

    data = request.json or {}
    hr_emp_id = data.get("hr_emp_id")
    emp_id = (data.get("emp_id") or "").strip().upper()
    balance = data.get("balance")

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

    with ENGINE.begin() as conn:
        hr_row = conn.execute(
            text("SELECT emp_id FROM employees WHERE emp_id = :hr_emp_id"),
            {"hr_emp_id": hr_emp_id},
        ).fetchone()
        if not hr_row:
            return err(f"HR employee '{hr_emp_id}' not found.", 404)

        emp_row = conn.execute(
            text("SELECT emp_id FROM employees WHERE emp_id = :emp_id"),
            {"emp_id": emp_id},
        ).fetchone()
        if not emp_row:
            return err(
                f"Employee '{emp_id}' not found in employees table. Only existing employees can have leave records.",
                404,
            )

        existing = conn.execute(
            text("SELECT balance FROM leaves WHERE emp_id = :emp_id"),
            {"emp_id": emp_id},
        ).fetchone()

        if existing:
            conn.execute(
                text("UPDATE leaves SET balance = :balance WHERE emp_id = :emp_id"),
                {"balance": balance, "emp_id": emp_id},
            )
            action = "updated"
        else:
            conn.execute(
                text("INSERT INTO leaves (emp_id, balance) VALUES (:emp_id, :balance)"),
                {"emp_id": emp_id, "balance": balance},
            )
            action = "added"

    df = pd.read_sql("SELECT * FROM leaves", ENGINE)
    os.makedirs("data", exist_ok=True)
    df.to_csv(LEAVE_CSV_PATH, index=False)

    logger.info(f"Leave balance {action} | emp_id={emp_id} | balance={balance} | by HR={hr_emp_id}")
    logger.info("leaves.csv synced")

    return jsonify(
        {
            "success": True,
            "message": f"Leave balance for {emp_id} has been {action} to {balance} days.",
            "emp_id": emp_id,
            "balance": balance,
            "action": action,
        }
    )
