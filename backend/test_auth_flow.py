"""
test_auth_flow.py

End-to-end test of the two-step, email-verified registration + two-step
login, run through Flask's test client (real HTTP request/response
cycle, no server process needed).

Run with:  python test_auth_flow.py

This is deliberately not just a "happy path" test — for a security
project, proving the WRONG cases are correctly rejected matters as much
as proving the right case works. That especially applies to the email
verification step, since its whole purpose is closing a real
impersonation gap (see docs/DEVLOG.md) — so the tests here specifically
probe: wrong email, missing email on file, wrong code, and reuse of an
already-registered ID.
"""

import os

os.environ["EVOTING_TEST_MODE"] = "1"

from database.db import init_db, DB_PATH
from database import queries
from security.totp import generate_totp
from services.auth_service import hash_student_id, hash_email
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

    STUDENT_ID = "79010020"
    EMAIL = "ashutosh@pmc.edu.np"
    PASSWORD = "correct-horse-battery-staple"

    # --- An unauthorized ID must be rejected at the start of registration ---
    r = client.post("/voter/register/start", json={"student_id": "00000000", "email": EMAIL, "password": PASSWORD})
    check("Unauthorized student ID rejected at registration", r.status_code == 400 and not r.get_json()["success"])

    # --- Admin adds this student, WITHOUT an email on file yet ---
    queries.add_authorized_voter(hash_student_id(STUDENT_ID), None)
    r = client.post("/voter/register/start", json={"student_id": STUDENT_ID, "email": EMAIL, "password": PASSWORD})
    check("Registration rejected when no email is on file for this ID", r.status_code == 400 and not r.get_json()["success"])

    # --- Admin (re-)uploads with the correct email now on file ---
    queries.add_authorized_voter(hash_student_id(STUDENT_ID), hash_email(EMAIL))

    # --- Wrong email at registration must be rejected ---
    r = client.post("/voter/register/start", json={"student_id": STUDENT_ID, "email": "someone-else@pmc.edu.np", "password": PASSWORD})
    check("Registration rejected when email doesn't match records", r.status_code == 400 and not r.get_json()["success"])

    # --- Correct email starts registration: dev_code returned (no SMTP configured in tests) ---
    r = client.post("/voter/register/start", json={"student_id": STUDENT_ID, "email": EMAIL, "password": PASSWORD})
    body = r.get_json()
    check("Registration starts successfully with the correct email", r.status_code == 200 and body["success"])
    pending_registration_token = body.get("pending_registration_token")
    dev_code = body.get("dev_code")
    check("A dev_code is returned when email sending isn't configured", bool(dev_code))
    check("No account exists yet after just starting registration", queries.get_voter_by_id_hash(hash_student_id(STUDENT_ID)) is None)

    # --- Wrong verification code must be rejected ---
    r = client.post("/voter/register/verify", json={"pending_registration_token": pending_registration_token, "code": "000000"})
    check("Wrong verification code rejected", r.status_code == 400 and not r.get_json()["success"])

    # --- Correct verification code completes registration ---
    r = client.post("/voter/register/verify", json={"pending_registration_token": pending_registration_token, "code": dev_code})
    body = r.get_json()
    check("Correct verification code completes registration", r.status_code == 201 and body["success"])
    totp_secret_hex = body.get("totp_secret")
    check("Registration returns a TOTP secret", bool(totp_secret_hex))

    # --- Re-verifying the same token again should fail (already registered) ---
    r = client.post("/voter/register/verify", json={"pending_registration_token": pending_registration_token, "code": dev_code})
    check("Re-using a spent registration token is rejected", r.status_code == 400 and not r.get_json()["success"])

    # --- Starting registration again for the same (now-registered) ID is rejected ---
    r = client.post("/voter/register/start", json={"student_id": STUDENT_ID, "email": EMAIL, "password": PASSWORD})
    check("Starting registration again for an already-registered ID is rejected", r.status_code == 400 and not r.get_json()["success"])

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

    # --- Admin uploads more authorized voters (ID+email pairs now), requires auth header ---
    new_voters = [{"student_id": "79010054", "email": "manish@pmc.edu.np"}, {"student_id": "79010119", "email": "snehal@pmc.edu.np"}]
    r = client.post("/admin/voters/upload", json={"voters": new_voters})
    check("Voter upload without admin token is rejected", r.status_code == 401)

    r = client.post("/admin/voters/upload", json={"voters": new_voters}, headers={"Authorization": f"Bearer {admin_token}"})
    check("Voter upload with valid admin token succeeds", r.status_code == 200 and r.get_json()["success"] and r.get_json()["added"] == 2)

    # --- Uploading an entry missing an email is skipped, not crashed on ---
    r = client.post("/admin/voters/upload", json={"voters": [{"student_id": "88888888"}]}, headers={"Authorization": f"Bearer {admin_token}"})
    check("Uploading a voter with no email is skipped cleanly", r.status_code == 200 and r.get_json()["added"] == 0 and r.get_json()["skipped"] == 1)

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
