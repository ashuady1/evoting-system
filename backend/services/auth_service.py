"""
services/auth_service.py

Business logic for registration and the two-step login. Routes (in
routes/voter_routes.py) stay thin — they just parse the request and call
these functions — so this logic can also be unit-tested directly without
going through HTTP (see test_auth_flow.py).
"""

import time

from security.hashing import generate_salt, hash_with_salt, verify_hash
from security.totp import generate_totp_secret, verify_totp
from security.config_secrets import SYSTEM_PEPPER, SERVER_SECRET_KEY
from security import tokens
from database import queries

PENDING_OTP_TTL_SECONDS = 300     # 5 minutes to enter the OTP after password step
VOTER_SESSION_TTL_SECONDS = 3600  # 1 hour session after full login


def hash_student_id(student_id: str) -> str:
    """
    Every place in the system that needs to look up a student by ID
    (admin upload, registration, login) must call this SAME function,
    since it's what makes the hashes comparable to each other.
    """
    return hash_with_salt(student_id.strip(), SYSTEM_PEPPER)


def register_voter(student_id: str, password: str) -> dict:
    if not student_id or not password:
        return {"success": False, "error": "Student ID and password are required."}
    if len(password) < 8:
        return {"success": False, "error": "Password must be at least 8 characters."}

    id_hash = hash_student_id(student_id)

    if not queries.is_authorized(id_hash):
        return {"success": False, "error": "This student ID is not on the authorized voter list."}

    if queries.get_voter_by_id_hash(id_hash) is not None:
        return {"success": False, "error": "This student ID has already been registered."}

    password_salt = generate_salt()
    password_hash = hash_with_salt(password, password_salt)
    totp_secret = generate_totp_secret()

    voter_id = queries.insert_voter(
        id_hash, password_hash, password_salt, totp_secret.hex()
    )

    return {
        "success": True,
        "voter_id": voter_id,
        # Shown ONCE at registration — in a full build this becomes a QR
        # code for an authenticator app. For now, the raw secret is enough
        # to demo generating live codes with security/totp.py.
        "totp_secret": totp_secret.hex(),
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
