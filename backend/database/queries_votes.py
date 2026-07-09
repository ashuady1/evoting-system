"""
database/queries_votes.py

Vote storage and the one-vote-per-election enforcement.

cast_vote_atomic() relies on the PRIMARY KEY on
voter_election_status(voter_id, election_id) to prevent double-voting
under concurrent requests, rather than manual locking. Two simultaneous
requests from the same voter both try to INSERT a row for that
(voter_id, election_id) pair; the database engine itself guarantees only
one of those inserts can succeed, and rejects the second with an
integrity error — atomically, at the storage engine level. This is both
simpler than manual locking and portable: it behaves identically on
SQLite and PostgreSQL, whereas an earlier version of this function used
SQLite-specific `BEGIN IMMEDIATE` locking that had no direct equivalent
when the project moved to supporting PostgreSQL for deployment.
"""

from .db import get_connection, IntegrityError


def has_voted(voter_id: int, election_id: int) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT has_voted FROM voter_election_status WHERE voter_id = ? AND election_id = ?",
            (voter_id, election_id),
        ).fetchone()
        return row is not None and row["has_voted"] == 1
    finally:
        conn.close()


def cast_vote_atomic(voter_id: int, election_id: int, encrypted_ballot: str, transaction_hash: str) -> bool:
    """
    Returns True if the vote was recorded, False if this voter had
    already voted in this election (checked and enforced atomically via
    the primary key constraint — see module docstring).
    """
    conn = get_connection()
    try:
        try:
            conn.execute(
                """INSERT INTO voter_election_status (voter_id, election_id, has_voted, voted_at)
                   VALUES (?, ?, 1, CURRENT_TIMESTAMP)""",
                (voter_id, election_id),
            )
        except IntegrityError:
            conn.rollback()
            return False

        # Deliberately no voter_id column here — see schema.sql / DEVLOG
        # Entry 3 for why "who voted" and "what they voted" stay separate.
        conn.execute(
            "INSERT INTO votes (election_id, encrypted_ballot, transaction_hash) VALUES (?, ?, ?)",
            (election_id, encrypted_ballot, transaction_hash),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_votes_for_election(election_id: int):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM votes WHERE election_id = ?", (election_id,)
        ).fetchall()
    finally:
        conn.close()


def count_voted_for_election(election_id: int) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM voter_election_status WHERE election_id = ? AND has_voted = 1",
            (election_id,),
        ).fetchone()
        return row["cnt"]
    finally:
        conn.close()
