"""
services/email_service.py

Sends registration verification codes by email, via two possible paths:

1. Brevo's HTTP API (preferred when configured) — a plain HTTPS POST,
   which works on hosts that block outbound SMTP ports entirely. This
   matters concretely: Render's free tier blocks outbound traffic on
   ports 25, 465, and 587 as of September 2025 (a deliberate anti-spam
   policy, not a bug), so raw SMTP simply cannot work there no matter
   which provider or credentials are used — every attempt times out.
   HTTPS (port 443) isn't blocked, since blocking it would break the
   platform's own normal web traffic. See docs/DEVLOG.md.

2. Plain SMTP (fallback) — still useful for a deployment target that
   doesn't block SMTP ports (e.g. a VPS instead of Render's free tier).
   Uses Python's built-in smtplib/email modules, no dependency needed.

CONFIGURATION (environment variables):
    Brevo HTTP API path (recommended for Render):
        BREVO_API_KEY        from Brevo dashboard -> SMTP & API -> API Keys
        BREVO_FROM_ADDRESS   must be a verified sender in Brevo's dashboard
        BREVO_FROM_NAME      optional, defaults to "Student Elections"

    SMTP path (for hosts that don't block SMTP ports):
        SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_ADDRESS

If BREVO_API_KEY is set, the Brevo HTTP API is used regardless of whether
SMTP variables are also present. If neither is configured,
send_verification_email() returns False, and the caller
(services/auth_service.py) falls back to handing the verification code
back directly in the API response instead — the same dev/demo-only
pattern used by routes/dev_routes.py's TOTP auto-fill.
"""

import os
import json
import smtplib
import urllib.request
import urllib.error
from email.mime.text import MIMEText

# ---- SMTP path (works on hosts that don't block outbound SMTP ports) -----

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_FROM_ADDRESS = os.environ.get("SMTP_FROM_ADDRESS", SMTP_USERNAME)

SMTP_CONFIGURED = bool(SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD)

# ---- Brevo HTTP API path (works on Render's free tier) --------------------

BREVO_API_KEY = os.environ.get("BREVO_API_KEY")
BREVO_FROM_ADDRESS = os.environ.get("BREVO_FROM_ADDRESS", SMTP_FROM_ADDRESS)
BREVO_FROM_NAME = os.environ.get("BREVO_FROM_NAME", "Student Elections")

BREVO_CONFIGURED = bool(BREVO_API_KEY and BREVO_FROM_ADDRESS)

EMAIL_SENDING_CONFIGURED = SMTP_CONFIGURED or BREVO_CONFIGURED


def _send_via_brevo_api(to_address: str, subject: str, body_text: str):
    payload = json.dumps({
        "sender": {"email": BREVO_FROM_ADDRESS, "name": BREVO_FROM_NAME},
        "to": [{"email": to_address}],
        "subject": subject,
        "textContent": body_text,
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        method="POST",
        headers={
            "api-key": BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status not in (200, 201):
                raise RuntimeError(f"Brevo API returned unexpected status {response.status}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Brevo API error {e.code}: {error_body}") from e


def _send_via_smtp(to_address: str, subject: str, body_text: str):
    message = MIMEText(body_text)
    message["Subject"] = subject
    message["From"] = SMTP_FROM_ADDRESS
    message["To"] = to_address

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_ADDRESS, [to_address], message.as_string())


def send_verification_email(to_address: str, code: str) -> bool:
    """
    Returns True if the email was actually sent, False if email sending
    isn't configured on this server (dev/demo mode — see module docstring).
    Raises if sending is configured but fails for some other reason (bad
    credentials, unverified sender, network issue) — the caller
    (services/auth_service.start_registration) catches this and turns it
    into a clean error message rather than letting it crash the request.
    """
    if not EMAIL_SENDING_CONFIGURED:
        return False

    subject = "Your voter registration verification code"
    body = (
        f"Your student council election verification code is: {code}\n\n"
        f"Enter this code to finish registering to vote. This code expires "
        f"in 15 minutes. If you didn't request this, you can ignore this email."
    )

    # Prefer the HTTP API when available — it works on hosts that block
    # outbound SMTP ports (see module docstring). Fall back to SMTP
    # otherwise (e.g. a VPS deployment with no such restriction).
    if BREVO_CONFIGURED:
        _send_via_brevo_api(to_address, subject, body)
    else:
        _send_via_smtp(to_address, subject, body)

    return True

