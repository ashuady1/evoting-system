"""
security/tokens.py

Signed, tamper-evident tokens for sessions and short-lived login steps —
our own minimal version of what a JWT library gives you, built on our
own hmac_sha256(). We use Python's built-in `json` and `base64` modules
for data formatting only (not security), the same way we use `os.urandom`
for entropy — they don't do any of the actual protecting; our HMAC does.

Format: "<base64url(json payload)>.<hex hmac signature>"

The signature covers the exact base64 bytes that get sent, so there's no
ambiguity from re-serializing JSON differently on encode vs decode.
"""

import json
import time
import base64

from .hmac_custom import hmac_sha256


def _constant_time_compare(a: str, b: str) -> bool:
    """
    Compares two strings without short-circuiting on the first mismatch.
    A naive `a == b` returns faster the earlier the strings diverge, which
    can leak information about the correct value through response timing.
    This walks the full length regardless of where a mismatch occurs.
    """
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


def create_token(payload: dict, ttl_seconds: int, secret: bytes) -> str:
    """Creates a signed token. Adds an 'exp' field automatically."""
    full_payload = dict(payload)
    full_payload["exp"] = time.time() + ttl_seconds

    payload_json = json.dumps(full_payload, sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json)
    signature = hmac_sha256(secret, payload_b64).hex()

    return payload_b64.decode("ascii") + "." + signature


def decode_token(token: str, secret: bytes) -> dict | None:
    """
    Verifies signature and expiry. Returns the payload dict if valid,
    or None if the token is malformed, tampered with, or expired.
    """
    try:
        payload_b64_str, signature = token.split(".")
    except ValueError:
        return None

    payload_b64 = payload_b64_str.encode("ascii")
    expected_signature = hmac_sha256(secret, payload_b64).hex()

    if not _constant_time_compare(signature, expected_signature):
        return None

    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (ValueError, UnicodeDecodeError):
        return None

    if payload.get("exp", 0) < time.time():
        return None

    return payload
