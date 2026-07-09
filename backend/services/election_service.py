"""
services/election_service.py

Business logic for setting up elections and serving ballots. Key rule
enforced here: an election can only move draft -> open once every
position has at least 2 candidates, and positions/candidates can only be
edited while still in draft. This stops an admin from changing the
ballot after voting has started, which would undermine the whole
integrity story no matter how good the crypto is.
"""

import json

from database import queries_elections as q
from database import queries as auth_q
from database import queries_votes as vote_q
from security import rsa_custom


def create_election(title: str, start_time: str, end_time: str) -> dict:
    if not title or not start_time or not end_time:
        return {"success": False, "error": "title, start_time, and end_time are required."}
    election_id = q.insert_election(title, start_time, end_time)
    return {"success": True, "election_id": election_id}


def add_position(election_id: int, title: str) -> dict:
    if not title:
        return {"success": False, "error": "Position title is required."}
    election = q.get_election(election_id)
    if election is None:
        return {"success": False, "error": "Election not found."}
    if election["status"] != "draft":
        return {"success": False, "error": "Positions can only be added while the election is in draft status."}
    position_id = q.insert_position(election_id, title)
    return {"success": True, "position_id": position_id}


MAX_PHOTO_BASE64_CHARS = 700_000  # ~500KB raw — generous, since the frontend resizes images before upload


def add_candidate(position_id: int, name: str, bio: str = "", photo_base64: str = None, photo_mime: str = None) -> dict:
    if not name:
        return {"success": False, "error": "Candidate name is required."}
    if photo_base64 and len(photo_base64) > MAX_PHOTO_BASE64_CHARS:
        return {"success": False, "error": "Photo is too large. Please use a smaller image."}
    position = q.get_position(position_id)
    if position is None:
        return {"success": False, "error": "Position not found."}
    election = q.get_election(position["election_id"])
    if election["status"] != "draft":
        return {"success": False, "error": "Candidates can only be added while the election is in draft status."}
    candidate_id = q.insert_candidate(position_id, name, bio, photo_base64, photo_mime)
    return {"success": True, "candidate_id": candidate_id}


def get_election_structure(election_id: int) -> dict | None:
    """Full nested view: election -> positions -> candidates. Used by both
    the admin review screen and (when open) the voter's ballot."""
    election = q.get_election(election_id)
    if election is None:
        return None

    positions = []
    for pos in q.get_positions_for_election(election_id):
        candidates = q.get_candidates_for_position(pos["id"])
        positions.append({
            "position_id": pos["id"],
            "title": pos["title"],
            "candidates": [
                {
                    "candidate_id": c["id"],
                    "name": c["name"],
                    "bio": c["bio"],
                    "photo": f"data:{c['photo_mime']};base64,{c['photo_base64']}" if c["photo_base64"] else None,
                }
                for c in candidates
            ],
        })

    return {
        "election_id": election["id"],
        "title": election["title"],
        "status": election["status"],
        "start_time": election["start_time"],
        "end_time": election["end_time"],
        "positions": positions,
    }


def open_election(election_id: int) -> dict:
    election = q.get_election(election_id)
    if election is None:
        return {"success": False, "error": "Election not found."}
    if election["status"] != "draft":
        return {"success": False, "error": f"Election is already {election['status']}."}

    positions = q.get_positions_for_election(election_id)
    if not positions:
        return {"success": False, "error": "Election needs at least one position before it can open."}

    for pos in positions:
        candidates = q.get_candidates_for_position(pos["id"])
        if len(candidates) < 2:
            return {
                "success": False,
                "error": f'Position "{pos["title"]}" needs at least 2 candidates before opening.',
            }

    q.update_election_status(election_id, "open")

    # Generate a fresh RSA keypair the moment voting opens. See
    # docs/DEVLOG.md Entry 10 re: where the private key lives and why
    # that's a named limitation, not a solved problem.
    public_key, private_key = rsa_custom.generate_keypair()
    q.store_election_rsa_keys(
        election_id,
        json.dumps({"e": public_key[0], "n": public_key[1]}),
        json.dumps({"d": private_key[0], "n": private_key[1]}),
    )

    return {"success": True}


def close_election(election_id: int) -> dict:
    election = q.get_election(election_id)
    if election is None:
        return {"success": False, "error": "Election not found."}
    if election["status"] != "open":
        return {"success": False, "error": "Only an open election can be closed."}
    q.update_election_status(election_id, "closed")
    return {"success": True}


def get_ballot_for_voting(election_id: int) -> dict:
    """What a logged-in voter sees. Only returns a ballot if voting is
    actually open right now — no peeking at draft ballots, no voting
    after close."""
    structure = get_election_structure(election_id)
    if structure is None:
        return {"success": False, "error": "Election not found."}
    if structure["status"] != "open":
        return {"success": False, "error": "This election is not currently open for voting."}
    return {"success": True, "ballot": structure}


def list_open_elections() -> list:
    elections = q.list_elections_by_status("open")
    return [
        {
            "election_id": e["id"],
            "title": e["title"],
            "start_time": e["start_time"],
            "end_time": e["end_time"],
        }
        for e in elections
    ]


def update_election(election_id: int, title: str = None, start_time: str = None, end_time: str = None) -> dict:
    """
    Lets an admin fix a typo or reschedule before an election opens.
    Deliberately restricted to draft elections — the same reasoning as
    the position/candidate lock: once voting is live, changing the title
    or schedule underneath it would undermine the whole integrity story.
    """
    election = q.get_election(election_id)
    if election is None:
        return {"success": False, "error": "Election not found."}
    if election["status"] != "draft":
        return {"success": False, "error": "Only draft elections (not yet opened) can be edited."}

    new_title = title.strip() if title else election["title"]
    new_start = start_time if start_time else election["start_time"]
    new_end = end_time if end_time else election["end_time"]
    if not new_title:
        return {"success": False, "error": "Title cannot be empty."}

    q.update_election_details(election_id, new_title, new_start, new_end)
    return {"success": True}


def list_open_elections_with_turnout() -> list:
    """
    Public-facing (no login required) summary of ongoing elections with
    a turnout percentage, for the home page. Deliberately exposes only
    aggregate participation counts — never individual votes or who cast
    them — same anonymity boundary as everywhere else in the system.
    """
    elections = q.list_elections_by_status("open")
    total_voters = auth_q.count_voters_total()

    result = []
    for e in elections:
        voted_count = vote_q.count_voted_for_election(e["id"])
        turnout_percent = round((voted_count / total_voters) * 100, 1) if total_voters > 0 else 0.0
        result.append({
            "election_id": e["id"],
            "title": e["title"],
            "start_time": e["start_time"],
            "end_time": e["end_time"],
            "voted_count": voted_count,
            "total_voters": total_voters,
            "turnout_percent": turnout_percent,
        })
    return result


def list_all_elections() -> list:
    elections = q.list_all_elections()
    return [
        {
            "election_id": e["id"],
            "title": e["title"],
            "status": e["status"],
            "start_time": e["start_time"],
            "end_time": e["end_time"],
        }
        for e in elections
    ]
