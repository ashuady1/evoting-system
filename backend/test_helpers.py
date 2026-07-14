"""
test_helpers.py

Shared helper for tests that need a fully registered and logged-in
voter. Centralized here (rather than duplicated in every test file) so
the two-step registration flow (email verification, then login) only
needs to be gotten right once — see docs/DEVLOG.md on the email
verification feature this replaced.

Not a test file itself — nothing in here runs on its own.
"""

from database import queries
from security.totp import generate_totp
from services.auth_service import hash_student_id, hash_email


def authorize_register_and_login(
    client, student_id: str, email: str, password: str = "correct-horse-battery-staple"
):
    """
    Full happy-path setup: authorizes (student_id, email), registers
    (including the email-verification step, using the dev_code fallback
    since no SMTP is configured in tests), and logs in.

    Returns a headers dict ready to use as `headers=` on further requests.
    """
    queries.add_authorized_voter(hash_student_id(student_id), hash_email(email))

    r = client.post("/voter/register/start", json={
        "student_id": student_id, "email": email, "password": password,
    })
    body = r.get_json()
    assert body.get("success"), f"registration start failed: {body}"
    pending_token = body["pending_registration_token"]
    code = body["dev_code"]  # dev-mode fallback since no SMTP is configured in tests

    r = client.post("/voter/register/verify", json={
        "pending_registration_token": pending_token, "code": code,
    })
    body = r.get_json()
    assert body.get("success"), f"registration verify failed: {body}"
    totp_secret_hex = body["totp_secret"]

    r = client.post("/voter/login", json={"student_id": student_id, "password": password})
    body = r.get_json()
    assert body.get("success"), f"login step 1 failed: {body}"
    pending_login_token = body["pending_token"]

    otp_code = generate_totp(bytes.fromhex(totp_secret_hex))
    r = client.post("/voter/login/verify-otp", json={
        "pending_token": pending_login_token, "code": otp_code,
    })
    body = r.get_json()
    assert body.get("success"), f"login step 2 failed: {body}"

    return {"Authorization": f"Bearer {body['session_token']}"}
