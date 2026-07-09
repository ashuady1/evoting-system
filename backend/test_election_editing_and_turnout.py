"""
test_election_editing_and_turnout.py

Covers two additions: editing an election's title/schedule (only while
still in draft) and the public (no-login) turnout endpoint used on the
voter home page.

Run with: python test_election_editing_and_turnout.py
"""

import os

from database.db import init_db, DB_PATH
from database import queries
from security.hashing import generate_salt, hash_with_salt
from security.totp import generate_totp
from services.auth_service import hash_student_id
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

    salt = generate_salt()
    queries.insert_admin("test_admin", hash_with_salt("admin-password-123", salt), salt)
    r = client.post("/admin/login", json={"username": "test_admin", "password": "admin-password-123"})
    admin_headers = {"Authorization": f"Bearer {r.get_json()['token']}"}

    # --- public elections empty before anything exists ---
    r = client.get("/voter/public/elections")
    check("Public elections endpoint requires no auth", r.status_code == 200)
    check("No elections listed yet", r.get_json()["elections"] == [])

    # --- create + edit while draft ---
    r = client.post("/admin/elections", json={
        "title": "Draft Title", "start_time": "2026-08-01T08:00", "end_time": "2026-08-01T18:00",
    }, headers=admin_headers)
    election_id = r.get_json()["election_id"]

    r = client.patch(f"/admin/elections/{election_id}", json={"title": "Corrected Title"}, headers=admin_headers)
    check("Editing a draft election succeeds", r.status_code == 200 and r.get_json()["success"])

    r = client.get(f"/admin/elections/{election_id}", headers=admin_headers)
    check("Edited title is persisted", r.get_json()["election"]["title"] == "Corrected Title")

    r = client.patch(f"/admin/elections/{election_id}", json={"start_time": "2026-08-02T09:00"}, headers=admin_headers)
    check("Partial edit (only start_time) succeeds", r.status_code == 200)
    r = client.get(f"/admin/elections/{election_id}", headers=admin_headers)
    check("Partial edit didn't clobber the title", r.get_json()["election"]["title"] == "Corrected Title")
    check("Partial edit updated start_time", r.get_json()["election"]["start_time"] == "2026-08-02T09:00")

    # --- build it out and open it ---
    r = client.post(f"/admin/elections/{election_id}/positions", json={"title": "President"}, headers=admin_headers)
    pres_id = r.get_json()["position_id"]
    client.post(f"/admin/positions/{pres_id}/candidates", json={"name": "Alice"}, headers=admin_headers)
    client.post(f"/admin/positions/{pres_id}/candidates", json={"name": "Bob"}, headers=admin_headers)
    r = client.post(f"/admin/elections/{election_id}/open", headers=admin_headers)
    check("Election opens", r.status_code == 200)

    # --- editing after open must fail ---
    r = client.patch(f"/admin/elections/{election_id}", json={"title": "Too Late"}, headers=admin_headers)
    check("Editing an open election is rejected", r.status_code == 400 and not r.get_json()["success"])
    r = client.get(f"/admin/elections/{election_id}", headers=admin_headers)
    check("Title unchanged after rejected edit", r.get_json()["election"]["title"] == "Corrected Title")

    # --- turnout starts at 0% with one registered voter ---
    def register_and_login(student_id):
        queries.add_authorized_voter(hash_student_id(student_id))
        client.post("/voter/register", json={"student_id": student_id, "password": "correct-horse-battery-staple"})
        r = client.post("/voter/login", json={"student_id": student_id, "password": "correct-horse-battery-staple"})
        pending = r.get_json()["pending_token"]
        voter = queries.get_voter_by_id_hash(hash_student_id(student_id))
        code = generate_totp(bytes.fromhex(voter["totp_secret"]))
        r = client.post("/voter/login/verify-otp", json={"pending_token": pending, "code": code})
        return {"Authorization": f"Bearer {r.get_json()['session_token']}"}

    voter_a = register_and_login("79010020")
    voter_b = register_and_login("79010054")

    r = client.get("/voter/public/elections")
    stats = r.get_json()["elections"][0]
    check("Turnout is 0% before anyone votes (2 registered, 0 voted)", stats["voted_count"] == 0 and stats["total_voters"] == 2)

    client.post(f"/voter/elections/{election_id}/vote", json={"selections": {str(pres_id): 1}}, headers=voter_a)

    r = client.get("/voter/public/elections")
    stats = r.get_json()["elections"][0]
    check("Turnout reflects 1 of 2 voters after a vote (50%)", stats["voted_count"] == 1 and stats["turnout_percent"] == 50.0)

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
