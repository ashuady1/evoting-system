"""
database/migrate_add_email_hash.py

Adds the `email_hash` column to an EXISTING authorized_voters table,
without touching any data already in it. See docs/DEVLOG.md Entry 19 for
why non-destructive migrations matter now that real deployed data
exists — same pattern as migrate_add_results_published.py.

Safe to run multiple times.

Usage:
    python database/migrate_add_email_hash.py                                  # local SQLite
    DATABASE_URL="postgresql://..." python database/migrate_add_email_hash.py  # Neon/production
"""

from db import get_connection, IS_POSTGRES


def _sqlite_has_column(conn, table, column) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in cursor.fetchall())


def migrate():
    conn = get_connection()
    try:
        if IS_POSTGRES:
            conn.execute("ALTER TABLE authorized_voters ADD COLUMN IF NOT EXISTS email_hash TEXT")
        else:
            if not _sqlite_has_column(conn, "authorized_voters", "email_hash"):
                conn.execute("ALTER TABLE authorized_voters ADD COLUMN email_hash TEXT")
        conn.commit()
        print("Migration complete: authorized_voters.email_hash is ready.")
        print("NOTE: any authorized_voters rows added BEFORE this migration have")
        print("email_hash = NULL. Those student IDs will need to be re-uploaded")
        print("(with an email this time) before their students can register —")
        print("see the admin dashboard's Authorized Voters tab.")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
