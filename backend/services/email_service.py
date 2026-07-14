"""
services/email_service.py

Sends registration verification codes by email. Uses Python's built-in
smtplib/email modules — no third-party email SDK needed, and it works
with any standard SMTP provider (Gmail's free SMTP with an app password,
or a free-tier transactional provider like Brevo).

CONFIGURATION (environment variables):
    SMTP_HOST              e.g. smtp.gmail.com
    SMTP_PORT              e.g. 587 (STARTTLS) — defaults to 587
    SMTP_USERNAME           the account to authenticate as
    SMTP_PASSWORD           an app password, NOT your normal account password
                            (Gmail: Google Account -> Security -> App Passwords)
    SMTP_FROM_ADDRESS      optional; defaults to SMTP_USERNAME

DEV / DEMO MODE: if these aren't set, send_verification_email() does not
attempt to send anything and returns False. The caller
(services/auth_service.py) treats that as a signal to hand the
verification code back directly in the API response instead — clearly
labeled as a development-only fallback, the same pattern already used by
routes/dev_routes.py for the TOTP auto-fill button. This means the
registration flow is fully demoable without any email account configured,
while still being a real, working feature once SMTP credentials are set
in production.
"""

import os
import smtplib
from email.mime.text import MIMEText

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_FROM_ADDRESS = os.environ.get("SMTP_FROM_ADDRESS", SMTP_USERNAME)

EMAIL_SENDING_CONFIGURED = bool(SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD)


def send_verification_email(to_address: str, code: str) -> bool:
    """
    Returns True if the email was actually sent, False if email sending
    isn't configured on this server (dev/demo mode — see module docstring).
    Raises if SMTP is configured but sending fails for some other reason
    (bad credentials, network issue, etc.) — that's a real error the
    caller should surface, not silently swallow.
    """
    if not EMAIL_SENDING_CONFIGURED:
        return False

    message = MIMEText(
        f"Your student council election verification code is: {code}\n\n"
        f"Enter this code to finish registering to vote. This code expires "
        f"in 15 minutes. If you didn't request this, you can ignore this email."
    )
    message["Subject"] = "Your voter registration verification code"
    message["From"] = SMTP_FROM_ADDRESS
    message["To"] = to_address

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_ADDRESS, [to_address], message.as_string())

    return True
