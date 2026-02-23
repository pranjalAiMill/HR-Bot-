import os
import pandas as pd
from sqlalchemy import create_engine, text

DB_PATH = "db/hr.db"


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

    # if os.path.exists("data/leaves.csv"):
    #     pd.read_csv("data/leaves.csv").to_sql(
    #         "leaves", engine, if_exists="replace", index=False
    #     )
    

    if os.path.exists("data/payslips.csv"):
        pd.read_csv("data/payslips.csv").to_sql(
            "payslips", engine, if_exists="replace", index=False
        )

    if os.path.exists("data/timesheets.csv"):
        pd.read_csv("data/timesheets.csv").to_sql(
            "timesheets", engine, if_exists="replace", index=False
        )

    if os.path.exists("data/performance_goals.csv"):
        pd.read_csv("data/performance_goals.csv").to_sql(
            "performance_goals", engine, if_exists="replace", index=False
        )

    if os.path.exists("data/recruitment.csv"):
        pd.read_csv("data/recruitment.csv").to_sql(
            "recruitment", engine, if_exists="replace", index=False
        )

    
    # ✅ leaves — seed ONLY ONCE, never overwrite live balance data
    _seed_if_empty("data/leaves.csv", "leaves")

    return engine
