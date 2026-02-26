import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_PATH = "db/hr.db"

INCIDENT_TYPES_SEED = [
    ("IT",         "IT Incident",         "Server, network, software, security breach"),
    ("HR",         "HR Incident",         "Workplace conflict, misconduct, policy violation"),
    ("FACILITIES", "Facilities Incident", "Power outage, AC failure, infrastructure, fire safety"),
    ("SAFETY",     "Safety Incident",     "Physical injury, hazard, near-miss"),
    ("FINANCE",    "Finance Incident",    "Fraud, billing error, data discrepancy"),
    ("COMPLIANCE", "Compliance Incident", "Legal, regulatory, or audit issue"),
    ("OTHERS",     "Other Incident",      "Anything that does not fit the above categories"),
]

def build_db():
    os.makedirs("db", exist_ok=True)
    engine = create_engine(f"sqlite:///{DB_PATH}")

    # ----------------------------
    # 1️⃣ Create ALL tables first
    # ----------------------------
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS payslips (
            emp_id TEXT,
            month TEXT,
            basic REAL,
            hra REAL,
            bonus REAL,
            pf REAL,
            tax REAL,
            deductions REAL,
            net_salary REAL
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS timesheets (
            emp_id TEXT,
            date TEXT,
            hours INTEGER,
            project TEXT
        )
        """))    

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS performance_goals (
            emp_id TEXT,
            goal_title TEXT,
            status TEXT,
            deadline TEXT
        )
        """))  

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS recruitment (
            candidate_id TEXT,
            position TEXT,
            status TEXT,
            assigned_hr TEXT
        )
        """))  

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS employees (
            emp_id TEXT PRIMARY KEY,
            name TEXT,
            department TEXT,
            email TEXT
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS salaries (
            emp_id TEXT PRIMARY KEY,
            salary INTEGER
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS leaves (
            emp_id TEXT PRIMARY KEY,
            balance INTEGER
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS leave_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            total_leaves_before INTEGER NOT NULL,
            leaves_requested INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL, 
            status TEXT NOT NULL DEFAULT 'PENDING_HR',
            jira_issue_key TEXT,
            total_leaves_after INTEGER
        )
        """))

        # ✅ Redesigned timesheet_log
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS timesheet_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            date TEXT NOT NULL,
            hours INTEGER NOT NULL,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING_HR',
            jira_issue_key TEXT,
            approved_by TEXT,
            approved_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(emp_id, project_id, date)
        )"""))

        # ✅ Projects master table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT
        )"""))

        # ✅ Employee ↔ Project allocations
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS project_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            hours_per_week INTEGER NOT NULL,
            UNIQUE(emp_id, project_id)
        )"""))

        # Service Request Log
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS service_request_log (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id         TEXT    NOT NULL,
            category       TEXT    NOT NULL,
            item           TEXT    NOT NULL,
            reason         TEXT    NOT NULL,
            status         TEXT    NOT NULL DEFAULT 'PENDING_HR',
            jira_issue_key TEXT,
            created_at     TEXT    NOT NULL,
            updated_at     TEXT    NOT NULL
        )"""))

        # Incident types master
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS incident_types (
            type_id     TEXT PRIMARY KEY,
            label       TEXT NOT NULL,
            description TEXT
        )"""))

        # Incidents
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS incidents (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id     TEXT UNIQUE NOT NULL,
            title           TEXT NOT NULL,
            description     TEXT NOT NULL,
            incident_type   TEXT NOT NULL REFERENCES incident_types(type_id),
            severity        TEXT NOT NULL DEFAULT 'Medium',
            status          TEXT NOT NULL DEFAULT 'Investigating',
            reported_by     TEXT NOT NULL,
            reported_at     TEXT NOT NULL,
            occurred_at     TEXT NOT NULL,
            resolved_at     TEXT,
            resolved_by     TEXT,
            jira_issue_key  TEXT
        )"""))

    # Seed incident_types once
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM incident_types")).scalar()
        if count == 0:
            conn.execute(
                text("INSERT INTO incident_types (type_id, label, description) VALUES (:t, :l, :d)"),
                [{"t": t, "l": l, "d": d} for t, l, d in INCIDENT_TYPES_SEED]
            )
            conn.commit()

    # Helper: only seeds if table is currently empty
    def _seed_if_empty(csv_path: str, table: str):
        if not os.path.exists(csv_path):
            return
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        if count == 0:
            pd.read_csv(csv_path).to_sql(table, engine, if_exists="append", index=False)

    # ----------------------------
    # 2️⃣ Seed master data (safe)
    # ----------------------------
    if os.path.exists("data/employees.csv"):
        pd.read_csv("data/employees.csv").to_sql(
            "employees", engine, if_exists="replace", index=False
        )

    if os.path.exists("data/salaries.csv"):
        pd.read_csv("data/salaries.csv").to_sql(
            "salaries", engine, if_exists="replace", index=False
        )

    if os.path.exists("data/payslips.csv"):
        pd.read_csv("data/payslips.csv").to_sql(
            "payslips", engine, if_exists="replace", index=False
        )

    if os.path.exists("data/performance_goals.csv"):
        pd.read_csv("data/performance_goals.csv").to_sql(
            "performance_goals", engine, if_exists="replace", index=False
        )

    if os.path.exists("data/recruitment.csv"):
        pd.read_csv("data/recruitment.csv").to_sql(
            "recruitment", engine, if_exists="replace", index=False
        )

    if os.path.exists("data/projects.csv"):
        pd.read_csv("data/projects.csv").to_sql(
            "projects", engine, if_exists="replace", index=False
        )

    if os.path.exists("data/project_allocations.csv"):
        pd.read_csv("data/project_allocations.csv").to_sql(
            "project_allocations", engine, if_exists="replace", index=False
        )

    # ✅ leaves — seed ONLY ONCE, never overwrite live balance data
    _seed_if_empty("data/leaves.csv", "leaves")
    _seed_if_empty("data/timesheets.csv", "timesheets")
    _seed_if_empty("data/service_request_log.csv", "service_request_log")

    return engine