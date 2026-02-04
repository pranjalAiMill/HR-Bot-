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
        CREATE TABLE IF NOT EXISTS leave_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            total_leaves_before INTEGER NOT NULL,
            leaves_requested INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            total_leaves_after INTEGER NOT NULL
        )
        """))

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

    if os.path.exists("data/leaves.csv"):
        pd.read_csv("data/leaves.csv").to_sql(
            "leaves", engine, if_exists="replace", index=False
        )

    return engine
