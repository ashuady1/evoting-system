"""
database/db.py

Supports two backends behind one interface:
  - SQLite (default): zero-setup local file, used unless DATABASE_URL is set.
  - PostgreSQL: used automatically when a DATABASE_URL environment variable
    is present (the standard way managed hosting platforms like Render or
    Railway hand you a database connection string).

Nothing else in the codebase needs to know which one is active — every
other file just calls get_connection(), run_query(), or run_insert() from
here. The two engines differ in a few real ways (placeholder syntax,
how you get a newly-inserted row's id back, schema syntax), and all of
that is handled in this one file.

Uses `psycopg` (v3), not the older `psycopg2` — psycopg2 is in
maintenance-only mode and its precompiled wheels lag behind new Python
releases (this caused a real deploy failure: Render's default Python was
newer than psycopg2-binary's wheel supported, raising an
"undefined symbol" ImportError no matter which Python version we tried
to pin). psycopg (v3) is actively maintained with wheels for current
Python versions, which sidesteps that problem entirely.
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "evoting.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
SCHEMA_PATH_POSTGRES = os.path.join(os.path.dirname(__file__), "schema_postgres.sql")

DATABASE_URL = os.environ.get("DATABASE_URL")
IS_POSTGRES = bool(DATABASE_URL)

if IS_POSTGRES:
    import psycopg
    import psycopg.rows
    IntegrityError = psycopg.IntegrityError
else:
    IntegrityError = sqlite3.IntegrityError


class _PostgresConnection:
    """
    Wraps a psycopg connection so it exposes the same .execute(sql, params)
    shortcut that sqlite3.Connection provides natively — this is what lets
    every other file in the codebase call conn.execute(...) without caring
    which database engine is actually running.
    """
    def __init__(self, pg_conn):
        self._conn = pg_conn

    def execute(self, query, params=()):
        cursor = self._conn.cursor(row_factory=psycopg.rows.dict_row)
        cursor.execute(query.replace("?", "%s"), params)
        return cursor

    def executescript(self, script):
        cursor = self._conn.cursor()
        cursor.execute(script)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_connection():
    """Returns a connection with a uniform .execute()/.commit()/.close()
    interface, backed by SQLite or PostgreSQL depending on DATABASE_URL."""
    if IS_POSTGRES:
        return _PostgresConnection(psycopg.connect(DATABASE_URL))

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Creates all tables (IF NOT EXISTS, so safe to re-run) from the
    schema matching whichever engine is active."""
    schema_path = SCHEMA_PATH_POSTGRES if IS_POSTGRES else SCHEMA_PATH
    conn = get_connection()
    try:
        with open(schema_path, "r") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()
    print(f"Database initialized ({'PostgreSQL via DATABASE_URL' if IS_POSTGRES else DB_PATH})")


def run_query(query, params=(), fetch=None):
    """
    For SELECT / UPDATE / DELETE, and INSERTs where the caller doesn't
    need the new row's id back.
        fetch: None, 'one', or 'all'
    """
    conn = get_connection()
    try:
        cursor = conn.execute(query, params)
        if fetch == "one":
            result = cursor.fetchone()
        elif fetch == "all":
            result = cursor.fetchall()
        else:
            result = None
        conn.commit()
        return result
    finally:
        conn.close()


def run_insert(query, params=()):
    """
    For INSERT statements where the caller needs the new row's integer id
    back. This is the one place SQLite and PostgreSQL genuinely diverge:
    SQLite hands this back via cursor.lastrowid automatically, while
    PostgreSQL requires an explicit `RETURNING id` clause on the INSERT
    itself. Handled once, here, rather than sprinkled through every query
    function.
    """
    conn = get_connection()
    try:
        if IS_POSTGRES:
            query = query.rstrip().rstrip(";") + " RETURNING id"
            cursor = conn.execute(query, params)
            new_id = cursor.fetchone()["id"]
        else:
            cursor = conn.execute(query, params)
            new_id = cursor.lastrowid
        conn.commit()
        return new_id
    finally:
        conn.close()


if __name__ == "__main__":
    # Running `python database/db.py` directly (re)builds the database.
    if IS_POSTGRES:
        init_db()
    else:
        if os.path.exists(DB_PATH):
            confirm = input(f"{DB_PATH} already exists. Overwrite? (y/n): ")
            if confirm.lower() != "y":
                exit()
            os.remove(DB_PATH)
        init_db()
