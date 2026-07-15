"""
services/auth_service.py

Business logic for registration and the two-step login. Routes (in
routes/voter_routes.py) stay thin — they just parse the request and call
these functions — so this logic can also be unit-tested directly without
going through HTTP (see test_auth_flow.py).
"""

import os
import time

from security.hashing import generate_salt, hash_with_salt, verify_hash
from security.totp import generate_totp_secret, verify_totp
from security.config_secrets import SYSTEM_PEPPER, SERVER_SECRET_KEY
from security import tokens
from database import queries
from services import email_service

PENDING_OTP_TTL_SECONDS = 300         # 5 minutes to enter the OTP after password step
VOTER_SESSION_TTL_SECONDS = 3600      # 1 hour session after full login
PENDING_REGISTRATION_TTL_SECONDS = 900  # 15 minutes to enter the emailed verification code
VERIFICATION_CODE_LENGTH = 6


def hash_student_id(student_id: str) -> str:
    """
    Every place in the system that needs to look up a student by ID
    (admin upload, registration, login) must call this SAME function,
    since it's what makes the hashes comparable to each other.
    """
    return hash_with_salt(student_id.strip(), SYSTEM_PEPPER)


def hash_email(email: str) -> str:
    """
    Same idea as hash_student_id: normalize first (trim + lowercase, so
    "Name@Example.com" and "name@example.com" hash identically) so a
    student typing their email slightly differently at registration than
    however the admin typed it during upload doesn't wrongly reject them.
    """
    return hash_with_salt(email.strip().lower(), SYSTEM_PEPPER)


def _generate_verification_code(length: int = VERIFICATION_CODE_LENGTH) -> str:
    """Random numeric code, e.g. '284913'. Uses the OS CSPRNG (same
    entropy source as every other random value in this system — see
    security/hashing.py's note on why os.urandom is the one place we
    don't hand-roll randomness ourselves)."""
    return "".join(str(os.urandom(1)[0] % 10) for _ in range(length))


def start_registration(student_id: str, email: str, password: str) -> dict:
    """
    Step 1 of registration. Validates the ID+email pair against the
    authorized list, then sends a verification code to the email address
    the student just typed — proving they control that inbox, not just
    that they know a student ID number (which is often not very secret).

    Nothing is written to the voters table yet. The intended password
    hash and TOTP secret are generated now but only carried inside a
    signed, short-lived token — see the module docstring in
    security/tokens.py — and only actually persisted once the code is
    verified in verify_registration(). This means an abandoned or failed
    registration attempt never leaves a half-created account behind.
    """
    if not student_id or not email or not password:
        return {"success": False, "error": "Student ID, email, and password are all required."}
    if "@" not in email or "." not in email.split("@")[-1]:
        return {"success": False, "error": "Please enter a valid email address."}
    if len(password) < 8:
        return {"success": False, "error": "Password must be at least 8 characters."}

    id_hash = hash_student_id(student_id)
    authorized = queries.get_authorized_voter(id_hash)

    if authorized is None:
        return {"success": False, "error": "This student ID is not on the authorized voter list."}
    if authorized["email_hash"] is None:
        return {"success": False, "error": "No email is on file for this student ID yet. Contact the election admin to have it added."}
    if hash_email(email) != authorized["email_hash"]:
        return {"success": False, "error": "That email doesn't match our records for this student ID."}
    if queries.get_voter_by_id_hash(id_hash) is not None:
        return {"success": False, "error": "This student ID has already been registered."}

    password_salt = generate_salt()
    password_hash = hash_with_salt(password, password_salt)
    totp_secret = generate_totp_secret()

    code = _generate_verification_code()
    code_salt = generate_salt()
    code_hash = hash_with_salt(code, code_salt)

    pending_token = tokens.create_token(
        {
            "scope": "pending_registration",
            "student_id_hash": id_hash,
            "password_hash": password_hash,
            "password_salt": password_salt,
            "totp_secret": totp_secret.hex(),
            "code_hash": code_hash,
            "code_salt": code_salt,
        },
        ttl_seconds=PENDING_REGISTRATION_TTL_SECONDS,
        secret=SERVER_SECRET_KEY,
    )

    result = {"success": True, "pending_registration_token": pending_token}

    try:
        sent = email_service.send_verification_email(email, code)
    except Exception as e:
        # A real SMTP failure (wrong credentials, unverified sender,
        # network issue) must not crash the whole request — that just
        # shows the person an opaque, unhelpful error. Log the real
        # exception server-side (visible in Render's Logs tab) so the
        # actual cause can be diagnosed, and return a clean, honest
        # message instead of letting it propagate as an unhandled 500.
        print(f"[auth_service] Failed to send verification email to {email!r}: {e!r}")
        return {
            "success": False,
            "error": "We couldn't send the verification email right now. Please try again in a moment, or contact the election admin if this keeps happening.",
        }

    if sent:
        result["message"] = f"A verification code was sent to {email}."
    else:
        # Dev/demo mode — see services/email_service.py. Clearly labeled,
        # never silently indistinguishable from a real send.
        result["dev_code"] = code
        result["dev_note"] = "Email sending isn't configured on this server, so here's the code directly (development/demo only)."

    return result


def verify_registration(pending_registration_token: str, code: str) -> dict:
    """Step 2 of registration: checks the emailed code and, only if
    correct, actually creates the voter account."""
    payload = tokens.decode_token(pending_registration_token, SERVER_SECRET_KEY)
    if not payload or payload.get("scope") != "pending_registration":
        return {"success": False, "error": "Registration session expired or invalid. Please start registration again."}

    expected_hash = hash_with_salt(code.strip(), payload["code_salt"])
    if expected_hash != payload["code_hash"]:
        return {"success": False, "error": "Incorrect verification code."}

    id_hash = payload["student_id_hash"]
    if queries.get_voter_by_id_hash(id_hash) is not None:
        # Handles the edge case of the same registration being verified
        # twice (e.g. a double-click) — fail cleanly rather than trying
        # to insert a duplicate row.
        return {"success": False, "error": "This student ID has already been registered."}

    voter_id = queries.insert_voter(
        id_hash, payload["password_hash"], payload["password_salt"], payload["totp_secret"]
    )

    return {
        "success": True,
        "voter_id": voter_id,
        "totp_secret": payload["totp_secret"],
    }


def login_step1(student_id: str, password: str) -> dict:
    id_hash = hash_student_id(student_id)
    voter = queries.get_voter_by_id_hash(id_hash)

    if voter is None:
        # Deliberately the same error message as a wrong password below —
        # distinguishing "unknown ID" from "wrong password" tells an
        # attacker which student IDs are registered.
        return {"success": False, "error": "Invalid student ID or password."}

    if not verify_hash(password, voter["password_salt"], voter["password_hash"]):
        queries.insert_login_event(voter["id"], None, None, success=False)
        return {"success": False, "error": "Invalid student ID or password."}

    pending_token = tokens.create_token(
        {"scope": "pending_otp", "voter_id": voter["id"], "issued_at": time.time()},
        ttl_seconds=PENDING_OTP_TTL_SECONDS,
        secret=SERVER_SECRET_KEY,
    )
    return {"success": True, "pending_token": pending_token}


def login_step2(pending_token: str, code: str, ip_hash: str, device_hash: str) -> dict:
    payload = tokens.decode_token(pending_token, SERVER_SECRET_KEY)
    if not payload or payload.get("scope") != "pending_otp":
        return {"success": False, "error": "Login session expired or invalid. Please log in again."}

    voter = queries.get_voter_by_id(payload["voter_id"])
    if voter is None:
        return {"success": False, "error": "Voter not found."}

    is_valid = verify_totp(bytes.fromhex(voter["totp_secret"]), code)

    issued_at = payload.get("issued_at")
    otp_seconds_taken = (time.time() - issued_at) if issued_at else None
    queries.insert_login_event(voter["id"], ip_hash, device_hash, success=is_valid, otp_seconds_taken=otp_seconds_taken)

    if not is_valid:
        return {"success": False, "error": "Incorrect authentication code."}

    session_token = tokens.create_token(
        {"scope": "voter_session", "voter_id": voter["id"], "device_hash": device_hash},
        ttl_seconds=VOTER_SESSION_TTL_SECONDS,
        secret=SERVER_SECRET_KEY,
    )
    return {"success": True, "session_token": session_token}


def validate_voter_session(session_token: str, device_hash: str) -> dict | None:
    """
    Used by future routes (ballot casting, etc.) to check a request is
    coming from a logged-in voter, on the same device that logged in.
    """
    payload = tokens.decode_token(session_token, SERVER_SECRET_KEY)
    if not payload or payload.get("scope") != "voter_session":
        return None
    if payload.get("device_hash") != device_hash:
        return None
    return payload


def list_authorized_voters() -> dict:
    """
    Admin-facing view of the authorized voter list. Shows a short
    fingerprint of each entry's hash (never the original student ID —
    the hash is one-way by design) plus whether that ID has registered.
    """
    rows = queries.list_authorized_voters()
    entries = [
        {
            "hash_fingerprint": row["student_id_hash"][:12],
            "added_at": str(row["added_at"]),
            "has_email": row["email_hash"] is not None,
            # SQLite returns 0/1 for this boolean expression, PostgreSQL
            # returns True/False — normalize so the API response is
            # identical regardless of which database is active.
            "is_registered": bool(row["is_registered"]),
        }
        for row in rows
    ]
    registered_count = sum(1 for e in entries if e["is_registered"])
    return {
        "success": True,
        "entries": entries,
        "total": len(entries),
        "registered_count": registered_count,
    }
