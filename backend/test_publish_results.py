"""
test_publish_results.py

Covers: publishing is rejected before an election is closed, public
results are invisible until published, published results show correct
candidate names and vote counts, and re-publishing is harmless.

Run with: python test_publish_results.py
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

    salt = generate_salt()
    queries.insert_admin("test_admin", hash_with_salt("admin-password-123", salt), salt)
    r = client.post("/admin/login", json={"username": "test_admin", "password": "admin-password-123"})
    admin_headers = {"Authorization": f"Bearer {r.get_json()['token']}"}

    r = client.post("/admin/elections", json={
        "title": "Publish Test Election", "start_time": "2026-08-01T08:00", "end_time": "2026-08-01T18:00",
    }, headers=admin_headers)
    election_id = r.get_json()["election_id"]

    r = client.post(f"/admin/elections/{election_id}/positions", json={"title": "President"}, headers=admin_headers)
    pres_id = r.get_json()["position_id"]
    r = client.post(f"/admin/positions/{pres_id}/candidates", json={"name": "Alice"}, headers=admin_headers)
    alice_id = r.get_json()["candidate_id"]
    r = client.post(f"/admin/positions/{pres_id}/candidates", json={"name": "Bob"}, headers=admin_headers)
    bob_id = r.get_json()["candidate_id"]

    client.post(f"/admin/elections/{election_id}/open", headers=admin_headers)

    r = client.post(f"/admin/elections/{election_id}/publish", headers=admin_headers)
    check("Publishing an open election is rejected", r.status_code == 400 and not r.get_json()["success"])

    voter_a = authorize_register_and_login(client, "79010020", "voter.a@pmc.edu.np")
    voter_b = authorize_register_and_login(client, "79010054", "voter.b@pmc.edu.np")
    voter_c = authorize_register_and_login(client, "79010119", "voter.c@pmc.edu.np")
    client.post(f"/voter/elections/{election_id}/vote", json={"selections": {str(pres_id): alice_id}}, headers=voter_a)
    client.post(f"/voter/elections/{election_id}/vote", json={"selections": {str(pres_id): alice_id}}, headers=voter_b)
    client.post(f"/voter/elections/{election_id}/vote", json={"selections": {str(pres_id): bob_id}}, headers=voter_c)

    r = client.get("/voter/public/results")
    check("No public results while election is still open", r.get_json()["elections"] == [])

    client.post(f"/admin/elections/{election_id}/close", headers=admin_headers)

    r = client.get("/voter/public/results")
    check("No public results when closed but not yet published", r.get_json()["elections"] == [])

    r = client.post(f"/admin/elections/{election_id}/publish", headers=admin_headers)
    check("Publishing a closed election succeeds", r.status_code == 200 and r.get_json()["success"])

    r = client.get("/voter/public/results")
    body = r.get_json()
    check("Published election now appears in public results", len(body["elections"]) == 1)
    result = body["elections"][0]
    check("Total votes correct", result["total_votes"] == 3)
    candidates = {c["name"]: c["votes"] for c in result["positions"][0]["candidates"]}
    check("Alice has 2 votes, Bob has 1", candidates == {"Alice": 2, "Bob": 1})
    check("Results are sorted with the leader first", result["positions"][0]["candidates"][0]["name"] == "Alice")
    check("No tampering reported", result["tampered_detected"] == 0)
    check("published_at timestamp is present", result["published_at"] is not None)

    r = client.get(f"/admin/elections/{election_id}", headers=admin_headers)
    detail = r.get_json()["election"]
    check("Admin election detail shows results_published=True", detail["results_published"] is True)
    check("Admin election detail shows a published_at timestamp", detail["published_at"] is not None)

    r = client.post(f"/admin/elections/{election_id}/publish", headers=admin_headers)
    check("Re-publishing an already-published election still succeeds", r.status_code == 200)
    r = client.get("/voter/public/results")
    check("Results still correctly visible after re-publishing", len(r.get_json()["elections"]) == 1)

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
