"""
test_ballot_flow.py

Full-circle test: open an election (which generates real RSA keys), have
three voters cast ballots, prove double-voting is blocked, close the
election, tally results by decrypting every vote, and prove a tampered
vote is detected rather than silently miscounted.

Run with: python test_ballot_flow.py
"""

import os

from database.db import init_db, DB_PATH, run_query
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

    # --- admin setup ---
    salt = generate_salt()
    queries.insert_admin("test_admin", hash_with_salt("admin-password-123", salt), salt)
    r = client.post("/admin/login", json={"username": "test_admin", "password": "admin-password-123"})
    admin_headers = {"Authorization": f"Bearer {r.get_json()['token']}"}

    # --- build the election ---
    r = client.post(
        "/admin/elections",
        json={"title": "2026 Student Council Election", "start_time": "2026-07-10T08:00", "end_time": "2026-07-10T18:00"},
        headers=admin_headers,
    )
    election_id = r.get_json()["election_id"]

    r = client.post(f"/admin/elections/{election_id}/positions", json={"title": "President"}, headers=admin_headers)
    president_id = r.get_json()["position_id"]
    r = client.post(f"/admin/elections/{election_id}/positions", json={"title": "Secretary"}, headers=admin_headers)
    secretary_id = r.get_json()["position_id"]

    r = client.post(f"/admin/positions/{president_id}/candidates", json={"name": "Alice"}, headers=admin_headers)
    alice_id = r.get_json()["candidate_id"]
    r = client.post(f"/admin/positions/{president_id}/candidates", json={"name": "Bob"}, headers=admin_headers)
    bob_id = r.get_json()["candidate_id"]
    r = client.post(f"/admin/positions/{secretary_id}/candidates", json={"name": "Carol"}, headers=admin_headers)
    carol_id = r.get_json()["candidate_id"]
    r = client.post(f"/admin/positions/{secretary_id}/candidates", json={"name": "Dave"}, headers=admin_headers)
    dave_id = r.get_json()["candidate_id"]

    r = client.post(f"/admin/elections/{election_id}/open", headers=admin_headers)
    check("Election opens successfully", r.status_code == 200 and r.get_json()["success"])

    election_row = run_query("SELECT * FROM elections WHERE id = ?", (election_id,), fetch="one")
    check("RSA keypair was generated and stored on open", election_row["rsa_public_key"] is not None and election_row["rsa_private_key"] is not None)

    # --- three voters ---
    voter_a_headers = authorize_register_and_login(client, "79010020", "voter.a@pmc.edu.np")
    voter_b_headers = authorize_register_and_login(client, "79010054", "voter.b@pmc.edu.np")
    voter_c_headers = authorize_register_and_login(client, "79010119", "voter.c@pmc.edu.np")

    # --- voter A votes: Alice for President, Carol for Secretary ---
    r = client.post(
        f"/voter/elections/{election_id}/vote",
        json={"selections": {str(president_id): alice_id, str(secretary_id): carol_id}},
        headers=voter_a_headers,
    )
    body = r.get_json()
    check("Voter A's vote is accepted", r.status_code == 201 and body["success"])
    check("Voter A's vote returns a transaction hash", bool(body.get("transaction_hash")))

    # --- voter A tries to vote again: must be rejected ---
    r = client.post(
        f"/voter/elections/{election_id}/vote",
        json={"selections": {str(president_id): bob_id, str(secretary_id): dave_id}},
        headers=voter_a_headers,
    )
    check("Voter A cannot vote a second time", r.status_code == 400 and not r.get_json()["success"])

    # --- voter B submits an incomplete ballot (missing a position): must be rejected ---
    r = client.post(
        f"/voter/elections/{election_id}/vote",
        json={"selections": {str(president_id): bob_id}},
        headers=voter_b_headers,
    )
    check("Incomplete ballot (missing a position) is rejected", r.status_code == 400 and not r.get_json()["success"])

    # --- voter B submits a candidate that doesn't belong to that position: must be rejected ---
    r = client.post(
        f"/voter/elections/{election_id}/vote",
        json={"selections": {str(president_id): carol_id, str(secretary_id): dave_id}},  # Carol isn't a President candidate
        headers=voter_b_headers,
    )
    check("Candidate mismatched to wrong position is rejected", r.status_code == 400 and not r.get_json()["success"])

    # --- voter B casts a valid, complete ballot: Bob for President, Dave for Secretary ---
    r = client.post(
        f"/voter/elections/{election_id}/vote",
        json={"selections": {str(president_id): bob_id, str(secretary_id): dave_id}},
        headers=voter_b_headers,
    )
    check("Voter B's valid vote is accepted", r.status_code == 201 and r.get_json()["success"])

    # --- voter C votes IDENTICALLY to voter A (Alice + Carol) ---
    r = client.post(
        f"/voter/elections/{election_id}/vote",
        json={"selections": {str(president_id): alice_id, str(secretary_id): carol_id}},
        headers=voter_c_headers,
    )
    check("Voter C's vote (identical choices to voter A) is accepted", r.status_code == 201 and r.get_json()["success"])

    # --- prove padding worked: A and C chose identically but ciphertexts must differ ---
    votes = run_query("SELECT * FROM votes WHERE election_id = ?", (election_id,), fetch="all")
    check("Three votes were recorded", len(votes) == 3)
    ciphertexts = [v["encrypted_ballot"] for v in votes]
    check("Identical ballots (voter A and voter C) produced different ciphertexts", len(set(ciphertexts)) == 3)

    # --- votes table stores no voter identifier at all ---
    check("Votes table has no voter_id column (anonymity by schema design)", "voter_id" not in votes[0].keys())

    # --- try to close before results, then tally ---
    r = client.post(f"/admin/elections/{election_id}/close", headers=admin_headers)
    check("Election closes successfully", r.status_code == 200 and r.get_json()["success"])

    r = client.get(f"/admin/elections/{election_id}/results", headers=admin_headers)
    body = r.get_json()
    check("Results tally succeeds after closing", r.status_code == 200 and body["success"])
    results = body["results"]
    check("President tally: Alice=2, Bob=1", results[str(president_id)] == {str(alice_id): 2, str(bob_id): 1} or results[president_id] == {alice_id: 2, bob_id: 1})
    check("Secretary tally: Carol=2, Dave=1", results[str(secretary_id)] == {str(carol_id): 2, str(dave_id): 1} or results[secretary_id] == {carol_id: 2, dave_id: 1})
    check("No tampering detected in a clean run", body["tampered_detected"] == 0)

    # --- simulate a tampered database record and confirm the tally catches it ---
    tampered_vote_id = votes[0]["id"]
    run_query("UPDATE votes SET encrypted_ballot = ? WHERE id = ?", (str(int(votes[0]["encrypted_ballot"]) + 2), tampered_vote_id))
    r = client.get(f"/admin/elections/{election_id}/results", headers=admin_headers)
    body = r.get_json()
    check("Tampering with a stored ballot is detected by the transaction hash check", body["tampered_detected"] == 1)
    check("Total vote count still reported accurately alongside the tamper flag", body["total_votes"] == 3)

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
