"""
test_full_demo_flow.py

Simulates the ENTIRE demo script end-to-end, calling the exact same
endpoints the frontend JS calls, in the exact order a live presentation
would: admin signs in, uploads voters, builds an election, opens it; a
voter registers, uses the dev auto-fill endpoint (same as the "Auto-fill
code (demo)" button), logs in, views the ballot, and votes; admin closes
the election and views results and the anomaly scan.

Run with: python test_full_demo_flow.py
"""

import os

from database.db import init_db, DB_PATH, get_connection
from database import queries
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


def first_candidate_id(position_id):
    row = get_connection().execute(
        "SELECT id FROM candidates WHERE position_id = ? LIMIT 1", (position_id,)
    ).fetchone()
    return row["id"]


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()

    client = app.test_client()

    # --- serve pages (what a browser loads first) ---
    check("Voter portal page loads", client.get("/").status_code == 200)
    check("Admin portal page loads", client.get("/admin").status_code == 200)

    # --- admin account bootstrap (out-of-band via create_admin.py in real use) ---
    from security.hashing import generate_salt, hash_with_salt
    salt = generate_salt()
    queries.insert_admin("election_admin", hash_with_salt("secure-admin-pw-1", salt), salt)

    r = client.post("/admin/login", json={"username": "election_admin", "password": "secure-admin-pw-1"})
    check("Admin signs in", r.status_code == 200 and r.get_json()["success"])
    admin_headers = {"Authorization": f"Bearer {r.get_json()['token']}"}

    # --- admin uploads authorized voters (same as pasting into the textarea) ---
    r = client.post("/admin/voters/upload", json={"voters": [
        {"student_id": "79010020", "email": "ashutosh@pmc.edu.np"},
        {"student_id": "79010054", "email": "manish@pmc.edu.np"},
        {"student_id": "79010119", "email": "snehal@pmc.edu.np"},
    ]}, headers=admin_headers)
    check("Admin uploads authorized voter list", r.status_code == 200 and r.get_json()["added"] == 3)

    # --- admin builds the election ---
    r = client.post("/admin/elections", json={
        "title": "2026 Student Council Election",
        "start_time": "2026-07-10T08:00",
        "end_time": "2026-07-10T18:00",
    }, headers=admin_headers)
    election_id = r.get_json()["election_id"]
    check("Admin creates election", r.status_code == 201)

    r = client.post(f"/admin/elections/{election_id}/positions", json={"title": "President"}, headers=admin_headers)
    president_id = r.get_json()["position_id"]
    r = client.post(f"/admin/elections/{election_id}/positions", json={"title": "General Secretary"}, headers=admin_headers)
    secretary_id = r.get_json()["position_id"]

    for name, bio in [("Ashutosh", "3rd year CS"), ("Manish", "4th year IT")]:
        client.post(f"/admin/positions/{president_id}/candidates", json={"name": name, "bio": bio}, headers=admin_headers)
    for name, bio in [("Snehal", "2nd year CS"), ("Priya", "3rd year IT")]:
        client.post(f"/admin/positions/{secretary_id}/candidates", json={"name": name, "bio": bio}, headers=admin_headers)

    r = client.post(f"/admin/elections/{election_id}/open", headers=admin_headers)
    check("Admin opens election (RSA keypair generated)", r.status_code == 200 and r.get_json()["success"])

    r = client.get("/admin/elections", headers=admin_headers)
    check("Admin dashboard can list all elections", r.status_code == 200 and len(r.get_json()["elections"]) == 1)

    # --- voter starts registration (same as the Register form) ---
    r = client.post("/voter/register/start", json={
        "student_id": "79010020", "email": "ashutosh@pmc.edu.np", "password": "correct-horse-battery-staple",
    })
    check("Voter starts registration", r.status_code == 200 and r.get_json()["success"])
    pending_registration_token = r.get_json()["pending_registration_token"]

    # --- voter clicks "Auto-fill code (dev)" on the verification step —
    #     same dev_code fallback the frontend uses when no SMTP is configured ---
    dev_code = r.get_json().get("dev_code")
    check("A dev_code is returned when email sending isn't configured", bool(dev_code))

    # --- voter completes registration by entering the code ---
    r = client.post("/voter/register/verify", json={
        "pending_registration_token": pending_registration_token, "code": dev_code,
    })
    check("Voter completes registration with the verification code", r.status_code == 201 and r.get_json()["success"])
    totp_secret = r.get_json()["totp_secret"]

    # --- voter logs in, step 1 ---
    r = client.post("/voter/login", json={"student_id": "79010020", "password": "correct-horse-battery-staple"})
    check("Voter login step 1 (password)", r.status_code == 200)
    pending_token = r.get_json()["pending_token"]

    # --- voter clicks "Auto-fill code (demo)" — same endpoint the button calls ---
    r = client.post("/dev/generate-otp", json={"secret": totp_secret})
    check("Dev auto-fill OTP endpoint works (same as the demo button)", r.status_code == 200 and len(r.get_json()["code"]) == 6)
    otp_code = r.get_json()["code"]

    # --- voter logs in, step 2 ---
    r = client.post("/voter/login/verify-otp", json={"pending_token": pending_token, "code": otp_code})
    check("Voter login step 2 (OTP)", r.status_code == 200 and r.get_json()["success"])
    voter_headers = {"Authorization": f"Bearer {r.get_json()['session_token']}"}

    # --- voter views open elections (same as the Elections list view) ---
    r = client.get("/voter/elections", headers=voter_headers)
    check("Voter sees the open election in the list", r.status_code == 200 and len(r.get_json()["elections"]) == 1)

    # --- voter opens the ballot ---
    r = client.get(f"/voter/elections/{election_id}/ballot", headers=voter_headers)
    check("Voter loads the ballot with both positions", r.status_code == 200 and len(r.get_json()["ballot"]["positions"]) == 2)

    # --- voter casts a vote (same as clicking "Cast my vote") ---
    selections = {
        str(president_id): first_candidate_id(president_id),
        str(secretary_id): first_candidate_id(secretary_id),
    }
    r = client.post(f"/voter/elections/{election_id}/vote", json={"selections": selections}, headers=voter_headers)
    check("Voter casts a vote and gets a transaction hash", r.status_code == 201 and bool(r.get_json().get("transaction_hash")))

    # --- admin closes the election and tallies results ---
    r = client.post(f"/admin/elections/{election_id}/close", headers=admin_headers)
    check("Admin closes the election", r.status_code == 200)

    r = client.get(f"/admin/elections/{election_id}/results", headers=admin_headers)
    check("Admin loads decrypted results", r.status_code == 200 and r.get_json()["total_votes"] == 1)

    # --- admin runs the security/anomaly scan (same as the "Scan now" button) ---
    r = client.get("/admin/security/anomalies", headers=admin_headers)
    check("Admin security scan endpoint responds", r.status_code == 200 and "flagged" in r.get_json())

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
