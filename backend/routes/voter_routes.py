"""
routes/voter_routes.py

HTTP layer only — parses requests and calls services/auth_service.py.
No business logic lives here.
"""

from functools import wraps

from flask import Blueprint, request, jsonify

from services import auth_service, election_service, ballot_service
from security.hashing import sha256

voter_bp = Blueprint("voter", __name__, url_prefix="/voter")


def _device_fingerprint(req) -> str:
    """Hashes User-Agent + IP into one fingerprint used to bind sessions."""
    raw = req.headers.get("User-Agent", "") + "|" + (req.remote_addr or "")
    return sha256(raw.encode("utf-8"))


def _ip_hash(req) -> str:
    return sha256((req.remote_addr or "").encode("utf-8"))


@voter_bp.route("/public/elections", methods=["GET"])
def public_elections():
    """
    No login required. Shows ongoing elections and turnout (participation
    percentage) on the home page — never individual votes or choices.
    """
    return jsonify({"success": True, "elections": election_service.list_open_elections_with_turnout()})


def require_voter_session(view_func):
    """Decorator: rejects the request unless a valid, non-expired session
    token is present AND was issued to this same device fingerprint."""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing session token."}), 401

        token = auth_header.split(" ", 1)[1]
        payload = auth_service.validate_voter_session(token, _device_fingerprint(request))
        if payload is None:
            return jsonify({"error": "Invalid or expired session, or this token was issued to a different device."}), 401

        request.voter_id = payload["voter_id"]
        return view_func(*args, **kwargs)
    return wrapper


@voter_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    result = auth_service.register_voter(
        data.get("student_id", ""), data.get("password", "")
    )
    return jsonify(result), (201 if result["success"] else 400)


@voter_bp.route("/login", methods=["POST"])
def login_step1():
    data = request.get_json(silent=True) or {}
    result = auth_service.login_step1(
        data.get("student_id", ""), data.get("password", "")
    )
    return jsonify(result), (200 if result["success"] else 401)


@voter_bp.route("/login/verify-otp", methods=["POST"])
def login_step2():
    data = request.get_json(silent=True) or {}
    result = auth_service.login_step2(
        data.get("pending_token", ""),
        data.get("code", ""),
        ip_hash=_ip_hash(request),
        device_hash=_device_fingerprint(request),
    )
    return jsonify(result), (200 if result["success"] else 401)


# ---- ballot viewing (requires a valid session) -----------------------------

@voter_bp.route("/elections", methods=["GET"])
@require_voter_session
def list_open_elections():
    return jsonify({"success": True, "elections": election_service.list_open_elections()})


@voter_bp.route("/elections/<int:election_id>/ballot", methods=["GET"])
@require_voter_session
def view_ballot(election_id):
    result = election_service.get_ballot_for_voting(election_id)
    return jsonify(result), (200 if result["success"] else 400)


@voter_bp.route("/elections/<int:election_id>/vote", methods=["POST"])
@require_voter_session
def cast_vote(election_id):
    data = request.get_json(silent=True) or {}
    raw_selections = data.get("selections", {})
    try:
        selections = {int(position_id): int(candidate_id) for position_id, candidate_id in raw_selections.items()}
    except (ValueError, AttributeError, TypeError):
        return jsonify({"success": False, "error": "selections must map position_id to candidate_id."}), 400

    result = ballot_service.cast_vote(request.voter_id, election_id, selections)
    return jsonify(result), (201 if result["success"] else 400)
