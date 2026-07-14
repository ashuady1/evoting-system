"""
test_election_flow.py

Tests election/position/candidate setup, the "can't open until every
position has 2+ candidates" business rule, and that ballot viewing is
actually gated behind a real voter session (not just present in the URL).

Run with: python test_election_flow.py
"""

import os

from database.db import init_db, DB_PATH
from database import queries
from security.hashing import generate_salt, hash_with_salt
from security.totp import generate_totp
from services.auth_service import hash_student_id
from test_helpers import authorize_register_and_login
from app import app

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"[PASS] {label}")
        passed += 1
    else:
        print(f"[FAIL] {label}")
        failed += 1


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()

    client = app.test_client()

    # --- bootstrap an admin session ---
    salt = generate_salt()
    queries.insert_admin("test_admin", hash_with_salt("admin-password-123", salt), salt)
    r = client.post("/admin/login", json={"username": "test_admin", "password": "admin-password-123"})
    admin_token = r.get_json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # --- create an election ---
    r = client.post(
        "/admin/elections",
        json={"title": "2026 Student Council Election", "start_time": "2026-07-10T08:00", "end_time": "2026-07-10T18:00"},
        headers=admin_headers,
    )
    body = r.get_json()
    check("Election created", r.status_code == 201 and body["success"])
    election_id = body["election_id"]

    # --- add positions ---
    r = client.post(f"/admin/elections/{election_id}/positions", json={"title": "President"}, headers=admin_headers)
    president_position_id = r.get_json()["position_id"]
    r = client.post(f"/admin/elections/{election_id}/positions", json={"title": "General Secretary"}, headers=admin_headers)
    secretary_position_id = r.get_json()["position_id"]
    check("Two positions added", president_position_id and secretary_position_id)

    # --- try to open with no candidates at all: must fail ---
    r = client.post(f"/admin/elections/{election_id}/open", headers=admin_headers)
    check("Cannot open election with zero candidates", r.status_code == 400 and not r.get_json()["success"])

    # --- add only 1 candidate to President: still must fail ---
    client.post(f"/admin/positions/{president_position_id}/candidates", json={"name": "Alice", "bio": "3rd year CS"}, headers=admin_headers)
    r = client.post(f"/admin/elections/{election_id}/open", headers=admin_headers)
    check("Cannot open election with a position having only 1 candidate", r.status_code == 400 and not r.get_json()["success"])

    # --- fill out both positions properly ---
    client.post(f"/admin/positions/{president_position_id}/candidates", json={"name": "Bob", "bio": "4th year IT"}, headers=admin_headers)
    client.post(f"/admin/positions/{secretary_position_id}/candidates", json={"name": "Carol", "bio": "2nd year CS"}, headers=admin_headers)
    client.post(f"/admin/positions/{secretary_position_id}/candidates", json={"name": "Dave", "bio": "3rd year IT"}, headers=admin_headers)

    r = client.post(f"/admin/elections/{election_id}/open", headers=admin_headers)
    check("Election opens once every position has 2+ candidates", r.status_code == 200 and r.get_json()["success"])

    # --- positions/candidates can no longer be edited once open ---
    r = client.post(f"/admin/elections/{election_id}/positions", json={"title": "Treasurer"}, headers=admin_headers)
    check("Cannot add a position after the election is open", r.status_code == 400 and not r.get_json()["success"])

    # --- a voter with no session cannot view the ballot ---
    r = client.get(f"/voter/elections/{election_id}/ballot")
    check("Ballot viewing without a session token is rejected", r.status_code == 401)

    # --- register + fully log in a voter ---
    voter_headers = authorize_register_and_login(client, "79010020", "s79010020@pmc.edu.np")

    # --- now the ballot should be visible, with both positions and all candidates ---
    r = client.get(f"/voter/elections/{election_id}/ballot", headers=voter_headers)
    body = r.get_json()
    check("Logged-in voter can view the open ballot", r.status_code == 200 and body["success"])
    positions = body["ballot"]["positions"]
    check("Ballot contains both positions", len(positions) == 2)
    check("President position lists 2 candidates", len(next(p for p in positions if p["title"] == "President")["candidates"]) == 2)
    check("Secretary position lists 2 candidates", len(next(p for p in positions if p["title"] == "General Secretary")["candidates"]) == 2)

    # --- a session token from a different "device" (different User-Agent) must be rejected ---
    r = client.get(
        f"/voter/elections/{election_id}/ballot",
        headers={**voter_headers, "User-Agent": "some-other-browser-entirely"},
    )
    check("Session token rejected when used from a different device fingerprint", r.status_code == 401)

    # --- close the election, ballot should no longer be viewable for voting ---
    client.post(f"/admin/elections/{election_id}/close", headers=admin_headers)
    r = client.get(f"/voter/elections/{election_id}/ballot", headers=voter_headers)
    check("Ballot no longer available once election is closed", r.status_code == 400 and not r.get_json()["success"])

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
