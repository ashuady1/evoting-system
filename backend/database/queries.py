"""
database/queries.py

Named query functions for authentication-related tables. Every query is
parameterized (no string-formatted SQL) — this file is what to point to
in the report as the SQL-injection defense.
"""

from .db import run_query, run_insert, IS_POSTGRES


# ---- authorized_voters -----------------------------------------------

def add_authorized_voter(id_hash: str):
    if IS_POSTGRES:
        run_query(
            "INSERT INTO authorized_voters (student_id_hash) VALUES (?) ON CONFLICT (student_id_hash) DO NOTHING",
            (id_hash,),
        )
    else:
        run_query(
            "INSERT OR IGNORE INTO authorized_voters (student_id_hash) VALUES (?)",
            (id_hash,),
        )


def is_authorized(id_hash: str) -> bool:
    row = run_query(
        "SELECT 1 FROM authorized_voters WHERE student_id_hash = ?",
        (id_hash,), fetch="one",
    )
    return row is not None


def list_authorized_voters():
    """
    Returns every authorized entry with its (one-way) hash and whether
    that hash has a matching registered voter yet. Never the original
    student ID — hashing here is genuinely one-way by design (see
    schema.sql), so the admin view can only ever show a fingerprint plus
    registration status, not the literal ID that was uploaded.
    """
    return run_query(
        """SELECT av.student_id_hash, av.added_at,
                  (v.id IS NOT NULL) AS is_registered
           FROM authorized_voters av
           LEFT JOIN voters v ON v.student_id_hash = av.student_id_hash
           ORDER BY av.added_at DESC""",
        fetch="all",
    )


def count_authorized_voters() -> int:
    row = run_query("SELECT COUNT(*) as cnt FROM authorized_voters", fetch="one")
    return row["cnt"]


# ---- voters -------------------------------------------------------------

def get_voter_by_id_hash(id_hash: str):
    return run_query(
        "SELECT * FROM voters WHERE student_id_hash = ?",
        (id_hash,), fetch="one",
    )


def get_voter_by_id(voter_id: int):
    return run_query(
        "SELECT * FROM voters WHERE id = ?",
        (voter_id,), fetch="one",
    )


def insert_voter(id_hash: str, password_hash: str, password_salt: str, totp_secret_hex: str) -> int:
    return run_insert(
        """INSERT INTO voters (student_id_hash, password_hash, password_salt, totp_secret)
           VALUES (?, ?, ?, ?)""",
        (id_hash, password_hash, password_salt, totp_secret_hex),
    )


# ---- login_events ---------------------------------------------------------

def insert_login_event(voter_id, ip_hash, device_fingerprint_hash, success: bool, otp_seconds_taken: float = None):
    return run_insert(
        """INSERT INTO login_events (voter_id, ip_hash, device_fingerprint_hash, success, otp_seconds_taken)
           VALUES (?, ?, ?, ?, ?)""",
        (voter_id, ip_hash, device_fingerprint_hash, 1 if success else 0, otp_seconds_taken),
    )


# ---- admins -------------------------------------------------------------

def get_admin_by_username(username: str):
    return run_query(
        "SELECT * FROM admins WHERE username = ?",
        (username,), fetch="one",
    )


def count_voters_total() -> int:
    row = run_query("SELECT COUNT(*) as cnt FROM voters", fetch="one")
    return row["cnt"]


def insert_admin(username: str, password_hash: str, salt: str) -> int:
    return run_insert(
        "INSERT INTO admins (username, password_hash, salt) VALUES (?, ?, ?)",
        (username, password_hash, salt),
    )
