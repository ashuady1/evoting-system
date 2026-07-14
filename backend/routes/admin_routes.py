"""
routes/admin_routes.py

Admin login uses password only, not TOTP — a deliberate scope decision
(see docs/DEVLOG.md Entry 7): admins are trusted campus staff acting from
managed machines, not remote voters, so the risk profile is different.
Flagged there as a reasonable place to extend the system, not as
something we're claiming is already fully hardened.
"""

from functools import wraps

from flask import Blueprint, request, jsonify

from database import queries
from services.auth_service import hash_student_id, hash_email, list_authorized_voters
from security.hashing import generate_salt, hash_with_salt, verify_hash
from security import tokens
from security.config_secrets import SERVER_SECRET_KEY
from services import election_service, ballot_service, anomaly_service

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_SESSION_TTL_SECONDS = 3600


def require_admin(view_func):
    """Decorator: rejects the request unless a valid admin session token
    is present in the Authorization header as 'Bearer <token>'."""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing admin token."}), 401

        token = auth_header.split(" ", 1)[1]
        payload = tokens.decode_token(token, SERVER_SECRET_KEY)
        if not payload or payload.get("scope") != "admin_session":
            return jsonify({"error": "Invalid or expired admin session."}), 401

        request.admin_id = payload["admin_id"]
        return view_func(*args, **kwargs)
    return wrapper


@admin_bp.route("/login", methods=["POST"])
def admin_login():
    data = request.get_json(silent=True) or {}
    admin = queries.get_admin_by_username(data.get("username", ""))

    if admin is None or not verify_hash(data.get("password", ""), admin["salt"], admin["password_hash"]):
        return jsonify({"success": False, "error": "Invalid credentials."}), 401

    token = tokens.create_token(
        {"scope": "admin_session", "admin_id": admin["id"]},
        ttl_seconds=ADMIN_SESSION_TTL_SECONDS,
        secret=SERVER_SECRET_KEY,
    )
    return jsonify({"success": True, "token": token})


@admin_bp.route("/voters/upload", methods=["POST"])
@require_admin
def upload_voters():
    """
    Accepts { "voters": [{"student_id": "79010020", "email": "a@b.edu"}, ...] }
    and adds each (hashed) to the authorized voter list. Email is required
    now — see docs/DEVLOG.md on why registration needs to prove email
    access, not just knowledge of a student ID. Re-uploading an ID that's
    already authorized updates its email (see queries.add_authorized_voter),
    which is the intended way to backfill entries added before this
    feature existed.
    """
    data = request.get_json(silent=True) or {}
    voters = data.get("voters", [])

    if not isinstance(voters, list) or not voters:
        return jsonify({"success": False, "error": "Provide a non-empty list of voters."}), 400

    added = 0
    skipped = []
    for entry in voters:
        student_id = str(entry.get("student_id", "")).strip() if isinstance(entry, dict) else ""
        email = str(entry.get("email", "")).strip() if isinstance(entry, dict) else ""
        if not student_id or not email or "@" not in email:
            skipped.append(entry)
            continue
        queries.add_authorized_voter(hash_student_id(student_id), hash_email(email))
        added += 1

    return jsonify({"success": True, "added": added, "skipped": len(skipped)})


@admin_bp.route("/voters/list", methods=["GET"])
@require_admin
def list_voters():
    return jsonify(list_authorized_voters())


# ---- election management ---------------------------------------------------

@admin_bp.route("/elections", methods=["POST"])
@require_admin
def create_election():
    data = request.get_json(silent=True) or {}
    result = election_service.create_election(
        data.get("title", ""), data.get("start_time", ""), data.get("end_time", "")
    )
    return jsonify(result), (201 if result["success"] else 400)


@admin_bp.route("/elections", methods=["GET"])
@require_admin
def list_elections():
    return jsonify({"success": True, "elections": election_service.list_all_elections()})


@admin_bp.route("/elections/<int:election_id>", methods=["GET"])
@require_admin
def view_election(election_id):
    structure = election_service.get_election_structure(election_id)
    if structure is None:
        return jsonify({"success": False, "error": "Election not found."}), 404
    return jsonify({"success": True, "election": structure})


@admin_bp.route("/elections/<int:election_id>", methods=["PATCH"])
@require_admin
def update_election(election_id):
    data = request.get_json(silent=True) or {}
    result = election_service.update_election(
        election_id, data.get("title"), data.get("start_time"), data.get("end_time")
    )
    return jsonify(result), (200 if result["success"] else 400)


@admin_bp.route("/elections/<int:election_id>/positions", methods=["POST"])
@require_admin
def add_position(election_id):
    data = request.get_json(silent=True) or {}
    result = election_service.add_position(election_id, data.get("title", ""))
    return jsonify(result), (201 if result["success"] else 400)


@admin_bp.route("/positions/<int:position_id>/candidates", methods=["POST"])
@require_admin
def add_candidate(position_id):
    data = request.get_json(silent=True) or {}
    result = election_service.add_candidate(
        position_id,
        data.get("name", ""),
        data.get("bio", ""),
        data.get("photo_base64"),
        data.get("photo_mime"),
    )
    return jsonify(result), (201 if result["success"] else 400)


@admin_bp.route("/elections/<int:election_id>/open", methods=["POST"])
@require_admin
def open_election(election_id):
    result = election_service.open_election(election_id)
    return jsonify(result), (200 if result["success"] else 400)


@admin_bp.route("/elections/<int:election_id>/close", methods=["POST"])
@require_admin
def close_election(election_id):
    result = election_service.close_election(election_id)
    return jsonify(result), (200 if result["success"] else 400)


@admin_bp.route("/elections/<int:election_id>/publish", methods=["POST"])
@require_admin
def publish_results(election_id):
    result = election_service.publish_results(election_id)
    return jsonify(result), (200 if result["success"] else 400)


@admin_bp.route("/elections/<int:election_id>/results", methods=["GET"])
@require_admin
def election_results(election_id):
    result = ballot_service.tally_election(election_id)
    return jsonify(result), (200 if result["success"] else 400)


@admin_bp.route("/security/anomalies", methods=["GET"])
@require_admin
def security_anomalies():
    """Runs Isolation Forest over all recorded login behavior and returns
    anything flagged as anomalous, most suspicious first."""
    flagged = anomaly_service.detect_anomalies()
    return jsonify({"success": True, "flagged": flagged, "count": len(flagged)})
