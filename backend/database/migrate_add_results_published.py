"""
database/migrate_add_results_published.py

Adds the `results_published` and `published_at` columns to an EXISTING
elections table, without touching any data already in it.

Why this exists instead of "just delete and re-run db.py": earlier schema
changes in this project happened before there was any real deployed data,
so wiping and recreating the local SQLite file was harmless. That's no
longer true once a project has a live database with real elections/voters
in it (e.g. on Neon) — recreating the schema from scratch would delete
everything. This script is the first genuinely non-destructive migration
in the project, and the pattern to follow for any future schema change
made after data exists.

Safe to run multiple times — checks whether each column already exists
before trying to add it.

Usage:
    python database/migrate_add_results_published.py            # local SQLite
    DATABASE_URL="postgresql://..." python database/migrate_add_results_published.py   # Neon/production
"""

from db import get_connection, IS_POSTGRES


def _sqlite_has_column(conn, table, column) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in cursor.fetchall())


def migrate():
    conn = get_connection()
    try:
        if IS_POSTGRES:
            # PostgreSQL supports "ADD COLUMN IF NOT EXISTS" directly —
            # naturally idempotent, no manual existence check needed.
            conn.execute("ALTER TABLE elections ADD COLUMN IF NOT EXISTS results_published INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE elections ADD COLUMN IF NOT EXISTS published_at TIMESTAMP")
        else:
            # SQLite has no "IF NOT EXISTS" for ADD COLUMN, so check first.
            if not _sqlite_has_column(conn, "elections", "results_published"):
                conn.execute("ALTER TABLE elections ADD COLUMN results_published INTEGER NOT NULL DEFAULT 0")
            if not _sqlite_has_column(conn, "elections", "published_at"):
                conn.execute("ALTER TABLE elections ADD COLUMN published_at TEXT")
        conn.commit()
        print("Migration complete: elections.results_published and elections.published_at are ready.")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
