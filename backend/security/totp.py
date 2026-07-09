"""
security/totp.py

TOTP (Time-based One-Time Password), per RFC 6238, built on our own
hmac_sha256(). This is the same algorithm used by apps like Google
Authenticator — a 6-digit code that changes every 30 seconds, derived
from a shared secret and the current time, without either side needing
to send the other any message.

How it works:
  1. Take the current Unix time, divide by the time step (30s), floor it.
     This gives a counter T that both the server and a correct client
     will always compute identically, as long as their clocks roughly agree.
  2. Encode T as an 8-byte big-endian integer.
  3. Compute HMAC-SHA256(secret, T_bytes) -> 32-byte digest.
  4. "Dynamic truncation": use the last nibble of the digest to pick a
     4-byte window inside it, mask off the top bit (to avoid sign issues),
     and reduce mod 10^digits to get a fixed-length numeric code.

Why a shared secret plus time, rather than a shared secret plus a counter
that increments on each use (HOTP): TOTP doesn't require the server and
the voter's device to stay in sync on "how many times has this been used,"
which is a real state-management headache. Both sides just need
reasonably accurate clocks.
"""

import os
import time

from .hmac_custom import hmac_sha256

DEFAULT_TIME_STEP = 30   # seconds each code is valid for
DEFAULT_DIGITS = 6       # standard TOTP code length


def generate_totp_secret(length: int = 20) -> bytes:
    """
    Generates a random shared secret for a voter at registration time.
    20 bytes (160 bits) is the RFC-recommended minimum for HMAC-SHA1-based
    TOTP; we keep the same size for HMAC-SHA256 for a comfortable margin.
    """
    return os.urandom(length)


def _dynamic_truncate(hmac_digest: bytes, digits: int) -> str:
    offset = hmac_digest[-1] & 0x0F
    fragment = hmac_digest[offset:offset + 4]
    binary_code = (
        ((fragment[0] & 0x7F) << 24)
        | ((fragment[1] & 0xFF) << 16)
        | ((fragment[2] & 0xFF) << 8)
        | (fragment[3] & 0xFF)
    )
    code = binary_code % (10 ** digits)
    return str(code).zfill(digits)


def generate_totp(secret: bytes, timestamp: float = None,
                   time_step: int = DEFAULT_TIME_STEP,
                   digits: int = DEFAULT_DIGITS) -> str:
    """Generates the TOTP code for `secret` at `timestamp` (defaults to now)."""
    if timestamp is None:
        timestamp = time.time()
    counter = int(timestamp // time_step)
    counter_bytes = counter.to_bytes(8, byteorder="big")
    digest = hmac_sha256(secret, counter_bytes)
    return _dynamic_truncate(digest, digits)


def verify_totp(secret: bytes, code: str, timestamp: float = None,
                 time_step: int = DEFAULT_TIME_STEP,
                 digits: int = DEFAULT_DIGITS, window: int = 1) -> bool:
    """
    Checks `code` against the secret. `window=1` allows the code from one
    step before or after the current one to also be accepted, to tolerate
    small clock drift or the voter being slightly slow to type it in.
    """
    if timestamp is None:
        timestamp = time.time()
    for offset in range(-window, window + 1):
        candidate_time = timestamp + (offset * time_step)
        if generate_totp(secret, candidate_time, time_step, digits) == code:
            return True
    return False


if __name__ == "__main__":
    # RFC 6238 Appendix B official test vectors for the SHA-256 mode.
    # These use an 8-digit code and a fixed 32-byte ASCII seed, specifically
    # so implementers can verify their code against known-correct output.
    seed_sha256 = b"12345678901234567890123456789012"  # 32 bytes, as specified

    rfc_vectors = [
        (59,          "46119246"),
        (1111111109,  "68084774"),
        (1111111111,  "67062674"),
        (1234567890,  "91819424"),
        (2000000000,  "90698825"),
        (20000000000, "77737706"),
    ]

    print("Validating our TOTP against official RFC 6238 SHA-256 test vectors...\n")
    all_passed = True
    for unix_time, expected in rfc_vectors:
        ours = generate_totp(seed_sha256, timestamp=unix_time, digits=8)
        status = "PASS" if ours == expected else "FAIL"
        if ours != expected:
            all_passed = False
        print(f"[{status}] T={unix_time:<12} expected={expected}  ours={ours}")

    print("\nALL TESTS PASSED" if all_passed else "\nSOME TESTS FAILED")

    # Demonstration of realistic usage: 6-digit code, verify with clock drift tolerance.
    print("\n--- Realistic usage demo (6-digit, current time) ---")
    demo_secret = generate_totp_secret()
    live_code = generate_totp(demo_secret)
    print(f"Generated code: {live_code}")
    print(f"Verifies correctly: {verify_totp(demo_secret, live_code)}")
    print(f"Wrong code rejected: {not verify_totp(demo_secret, '000000')}")
