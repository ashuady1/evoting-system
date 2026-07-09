"""
security/config_secrets.py

Manages two persistent secrets:

1. SERVER_SECRET_KEY — signs session tokens (see tokens.py). If this
   leaked, an attacker could forge session tokens for anyone.
2. SYSTEM_PEPPER — a fixed value combined with every student ID before
   hashing (see services/auth_service.hash_student_id). Unlike a
   password salt (random per user, so identical passwords still hash
   differently), the pepper must be THE SAME for every ID, because we
   need to compute the same hash twice: once when the admin uploads the
   authorized list, and again when the student registers, so they match.

   NAMED LIMITATION: because the pepper is fixed and student IDs live in
   a small, guessable numeric range (e.g. 7-8 digits following a known
   campus format), this does not make IDs unguessable the way a random
   salt makes passwords resistant to precomputed rainbow tables — someone
   with the pepper could hash every plausible ID and check for matches.
   Its purpose is narrower: keep raw IDs out of the database and support
   exact-match lookups, not to make IDs cryptographically secret. Worth a
   sentence in the report rather than pretending otherwise.

LOCAL DEV vs. PRODUCTION:
Locally, both secrets are generated once with os.urandom() and persisted
as hex in backend/security/.secrets/ — convenient, zero setup.

In production (see docs/DEVLOG.md deployment entry), files on disk often
aren't reliably persistent — a hosting platform can restart your app in
a fresh container at any time, silently generating a NEW secret and
invalidating every active session, or worse, losing the RSA private key
for an open election. So in production, set these as environment
variables instead (generate them once locally, paste the hex value into
your hosting platform's dashboard): SERVER_SECRET_KEY_HEX and
SYSTEM_PEPPER_HEX. If those env vars are present, they're used directly
and nothing is written to disk.
"""

import os

_SECRETS_DIR = os.path.join(os.path.dirname(__file__), ".secrets")
os.makedirs(_SECRETS_DIR, exist_ok=True)


def _get_or_create_secret(filename: str, env_var: str, length: int = 32) -> bytes:
    env_value = os.environ.get(env_var)
    if env_value:
        return bytes.fromhex(env_value)

    path = os.path.join(_SECRETS_DIR, filename)
    if os.path.exists(path):
        with open(path, "r") as f:
            return bytes.fromhex(f.read().strip())
    secret = os.urandom(length)
    with open(path, "w") as f:
        f.write(secret.hex())
    return secret


SERVER_SECRET_KEY: bytes = _get_or_create_secret("server_secret.key", "SERVER_SECRET_KEY_HEX")
SYSTEM_PEPPER: str = _get_or_create_secret("system_pepper.key", "SYSTEM_PEPPER_HEX").hex()
