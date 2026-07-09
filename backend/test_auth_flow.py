"""
test_auth_flow.py

End-to-end test of registration + two-step login, run through Flask's
test client (real HTTP request/response cycle, no server process needed).

Run with:  python test_auth_flow.py

This is deliberately not just a "happy path" test — for a security
project, proving the WRONG cases are correctly rejected matters as much
as proving the right case works.
"""

import os

# Use a throwaway database for this test run so it doesn't collide with
# whatever data is in the real dev database.
os.environ["EVOTING_TEST_MODE"] = "1"

from database.db import init_db, DB_PATH
from database import queries
from security.totp import generate_totp
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
    # Fresh database for a clean, repeatable test run.
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()

    client = app.test_client()

    STUDENT_ID = "79010020"
    PASSWORD = "correct-horse-battery-staple"

    # --- An unauthorized ID must be rejected at registration ---
    r = client.post("/voter/register", json={"student_id": "00000000", "password": PASSWORD})
    check("Unauthorized student ID rejected at registration", r.status_code == 400 and not r.get_json()["success"])

    # --- Admin adds this student to the authorized list ---
    queries.add_authorized_voter(__import__("services.auth_service", fromlist=["hash_student_id"]).hash_student_id(STUDENT_ID))

    # --- Registration should now succeed ---
    r = client.post("/voter/register", json={"student_id": STUDENT_ID, "password": PASSWORD})
    body = r.get_json()
    check("Authorized student ID can register", r.status_code == 201 and body["success"])
    totp_secret_hex = body.get("totp_secret")
    check("Registration returns a TOTP secret", bool(totp_secret_hex))

    # --- Duplicate registration should be rejected ---
    r = client.post("/voter/register", json={"student_id": STUDENT_ID, "password": PASSWORD})
    check("Duplicate registration rejected", r.status_code == 400 and not r.get_json()["success"])

    # --- Login step 1: wrong password rejected ---
    r = client.post("/voter/login", json={"student_id": STUDENT_ID, "password": "wrong-password"})
    check("Wrong password rejected", r.status_code == 401 and not r.get_json()["success"])

    # --- Login step 1: correct password succeeds, returns pending token ---
    r = client.post("/voter/login", json={"student_id": STUDENT_ID, "password": PASSWORD})
    body = r.get_json()
    check("Correct password accepted at step 1", r.status_code == 200 and body["success"])
    pending_token = body.get("pending_token")

    # --- Login step 2: wrong OTP code rejected ---
    r = client.post("/voter/login/verify-otp", json={"pending_token": pending_token, "code": "000000"})
    check("Wrong OTP code rejected", r.status_code == 401 and not r.get_json()["success"])

    # --- Login step 2: correct OTP code succeeds, returns session token ---
    correct_code = generate_totp(bytes.fromhex(totp_secret_hex))
    r = client.post("/voter/login/verify-otp", json={"pending_token": pending_token, "code": correct_code})
    body = r.get_json()
    check("Correct OTP code accepted, session issued", r.status_code == 200 and body["success"] and body.get("session_token"))

    # --- A pending token can't be reused as if it were a full session (wrong scope) ---
    from security import tokens
    from security.config_secrets import SERVER_SECRET_KEY
    from services.auth_service import validate_voter_session
    fake_device_hash = "irrelevant"
    check(
        "A pending_otp token is rejected by session validation",
        validate_voter_session(pending_token, fake_device_hash) is None
    )

    # --- Admin flow: no admin exists yet, so login should fail cleanly ---
    r = client.post("/admin/login", json={"username": "nonexistent", "password": "whatever"})
    check("Admin login with unknown username rejected", r.status_code == 401)

    # --- Create an admin directly (simulating create_admin.py) and log in ---
    from security.hashing import generate_salt, hash_with_salt
    salt = generate_salt()
    queries.insert_admin("test_admin", hash_with_salt("admin-password-123", salt), salt)
    r = client.post("/admin/login", json={"username": "test_admin", "password": "admin-password-123"})
    body = r.get_json()
    check("Admin login succeeds with correct credentials", r.status_code == 200 and body["success"])
    admin_token = body.get("token")

    # --- Admin uploads more authorized voters, requires auth header ---
    r = client.post("/admin/voters/upload", json={"student_ids": ["79010054", "79010119"]})
    check("Voter upload without admin token is rejected", r.status_code == 401)

    r = client.post(
        "/admin/voters/upload",
        json={"student_ids": ["79010054", "79010119"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    check("Voter upload with valid admin token succeeds", r.status_code == 200 and r.get_json()["success"])

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
