"""
database/queries_elections.py

Parameterized queries for elections, positions, and candidates. Kept in
a separate file from queries.py (auth-related) just to keep each file
focused on one area of the schema.
"""

from .db import run_query, run_insert


# ---- elections ------------------------------------------------------------

def insert_election(title: str, start_time: str, end_time: str) -> int:
    return run_insert(
        "INSERT INTO elections (title, start_time, end_time) VALUES (?, ?, ?)",
        (title, start_time, end_time),
    )


def get_election(election_id: int):
    return run_query("SELECT * FROM elections WHERE id = ?", (election_id,), fetch="one")


def update_election_status(election_id: int, status: str):
    run_query("UPDATE elections SET status = ? WHERE id = ?", (status, election_id))


def publish_election_results(election_id: int):
    run_query(
        "UPDATE elections SET results_published = 1, published_at = CURRENT_TIMESTAMP WHERE id = ?",
        (election_id,),
    )


def list_published_closed_elections():
    return run_query(
        "SELECT * FROM elections WHERE status = 'closed' AND results_published = 1 ORDER BY id DESC",
        fetch="all",
    )


def update_election_details(election_id: int, title: str, start_time: str, end_time: str):
    run_query(
        "UPDATE elections SET title = ?, start_time = ?, end_time = ? WHERE id = ?",
        (title, start_time, end_time, election_id),
    )


def list_elections_by_status(status: str):
    return run_query("SELECT * FROM elections WHERE status = ?", (status,), fetch="all")


def list_all_elections():
    return run_query("SELECT * FROM elections ORDER BY id DESC", fetch="all")


def store_election_rsa_keys(election_id: int, public_key_json: str, private_key_json: str):
    run_query(
        "UPDATE elections SET rsa_public_key = ?, rsa_private_key = ? WHERE id = ?",
        (public_key_json, private_key_json, election_id),
    )


# ---- positions --------------------------------------------------------------

def insert_position(election_id: int, title: str) -> int:
    return run_insert(
        "INSERT INTO positions (election_id, title) VALUES (?, ?)",
        (election_id, title),
    )


def get_position(position_id: int):
    return run_query("SELECT * FROM positions WHERE id = ?", (position_id,), fetch="one")


def get_positions_for_election(election_id: int):
    return run_query(
        "SELECT * FROM positions WHERE election_id = ?", (election_id,), fetch="all"
    )


# ---- candidates ------------------------------------------------------------

def insert_candidate(position_id: int, name: str, bio: str, photo_base64: str = None, photo_mime: str = None) -> int:
    return run_insert(
        "INSERT INTO candidates (position_id, name, bio, photo_base64, photo_mime) VALUES (?, ?, ?, ?, ?)",
        (position_id, name, bio, photo_base64, photo_mime),
    )


def get_candidates_for_position(position_id: int):
    return run_query(
        "SELECT * FROM candidates WHERE position_id = ?", (position_id,), fetch="all"
    )


def get_candidate(candidate_id: int):
    return run_query("SELECT * FROM candidates WHERE id = ?", (candidate_id,), fetch="one")
