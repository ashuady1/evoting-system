"""
routes/dev_routes.py

DEMO / DEVELOPMENT CONVENIENCE ONLY.

/dev/generate-otp computes the current TOTP code for a given secret. A
real authentication factor is only meaningful if the server can't just
hand out the code on request — so this endpoint, by definition, does not
belong in any real deployment. It exists purely so this project can be
demoed live (registering and logging in several test voters in a row)
without needing a separate phone running an authenticator app for each
one.

See docs/DEVLOG.md for this being logged as a named scope decision.
Before any real deployment, delete this file and its registration in
app.py.
"""

from flask import Blueprint, request, jsonify

from security.totp import generate_totp

dev_bp = Blueprint("dev", __name__, url_prefix="/dev")


@dev_bp.route("/generate-otp", methods=["POST"])
def generate_otp():
    data = request.get_json(silent=True) or {}
    secret_hex = data.get("secret", "")
    try:
        code = generate_totp(bytes.fromhex(secret_hex))
        return jsonify({"success": True, "code": code})
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid secret."}), 400
