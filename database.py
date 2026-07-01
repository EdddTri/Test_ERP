"""
Database access layer for the Job-Shop ERP demo.

Keeps everything intentionally simple: a single SQLite file, tiny query/execute
helpers, and an idempotent bootstrap() that creates the schema and seeds sample
data on first run so `streamlit run Home.py` works with zero manual setup.
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "db")
DB_PATH = os.path.join(DB_DIR, "erp.db")
SCHEMA_PATH = os.path.join(DB_DIR, "schema.sql")


def get_connection():
    """Return a SQLite connection with dict-like rows and FK enforcement."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query(sql, params=()):
    """Run a SELECT and return a list of plain dict rows.

    Plain dicts (not sqlite3.Row) so results are picklable/deep-copyable —
    Streamlit requires this when rows are used as widget options.
    """
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def query_one(sql, params=()):
    """Run a SELECT and return the first row as a dict (or None)."""
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    """Run an INSERT/UPDATE/DELETE and return lastrowid."""
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _create_schema(conn):
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


def bootstrap():
    """
    Ensure the DB exists, has the schema, and is seeded.

    Safe to call on every page load — it only seeds when the DB is empty.
    """
    fresh = not os.path.exists(DB_PATH)
    conn = get_connection()
    try:
        _create_schema(conn)
        # Seed only when there are no customers yet (first run).
        count = conn.execute("SELECT COUNT(*) FROM Customers").fetchone()[0]
        if count == 0:
            from db.seed import seed_data
            seed_data(conn)
    finally:
        conn.close()
    return fresh
