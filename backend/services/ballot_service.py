"""
services/ballot_service.py

Encodes a voter's selections into a compact ballot, validates it against
the actual election structure, encrypts it with padding, and stores it
with a tamper-evident transaction hash. Also provides tallying (decrypt +
count) for after an election closes.
"""

import json

from database import queries_elections as q
from database import queries_votes as vq
from security import rsa_custom
from security.hashing import sha256


def _load_public_key(election_row):
    data = json.loads(election_row["rsa_public_key"])
    return (data["e"], data["n"])


def _load_private_key(election_row):
    data = json.loads(election_row["rsa_private_key"])
    return (data["d"], data["n"])


def encode_ballot(election_id: int, selections: dict) -> bytes:
    """
    Compact format: "E<election_id>|P<position_id>:C<candidate_id>|...".
    Sorted by position_id so identical selections always encode to the
    identical plaintext (the padding, not the encoding, is what makes
    ciphertexts unique — see rsa_custom.encrypt_ballot).
    """
    parts = [f"E{election_id}"] + [
        f"P{pid}:C{cid}" for pid, cid in sorted(selections.items())
    ]
    return "|".join(parts).encode("utf-8")


def decode_ballot(plaintext: bytes) -> dict:
    text = plaintext.decode("utf-8")
    parts = text.split("|")
    election_id = int(parts[0][1:])
    selections = {}
    for part in parts[1:]:
        pos_str, cand_str = part.split(":")
        selections[int(pos_str[1:])] = int(cand_str[1:])
    return {"election_id": election_id, "selections": selections}


def cast_vote(voter_id: int, election_id: int, selections: dict) -> dict:
    election = q.get_election(election_id)
    if election is None:
        return {"success": False, "error": "Election not found."}
    if election["status"] != "open":
        return {"success": False, "error": "This election is not currently open for voting."}
    if vq.has_voted(voter_id, election_id):
        return {"success": False, "error": "You have already voted in this election."}

    # Ballot must cover exactly the positions in this election — no more,
    # no fewer — and each choice must be a real candidate for that position.
    positions = q.get_positions_for_election(election_id)
    required_position_ids = {p["id"] for p in positions}
    if set(selections.keys()) != required_position_ids:
        return {"success": False, "error": "You must select exactly one candidate for every position."}

    for position_id, candidate_id in selections.items():
        valid_candidate_ids = {c["id"] for c in q.get_candidates_for_position(position_id)}
        if candidate_id not in valid_candidate_ids:
            return {"success": False, "error": f"Candidate {candidate_id} is not valid for position {position_id}."}

    plaintext = encode_ballot(election_id, selections)
    public_key = _load_public_key(election)
    ciphertext_int = rsa_custom.encrypt_ballot(plaintext, public_key)

    # Transaction hash: a seal over the ciphertext. If the stored
    # encrypted_ballot is later altered, recomputing this hash from the
    # (altered) ciphertext will no longer match what's stored — this is
    # exactly the tamper-detection mechanism described in the proposal.
    transaction_hash = sha256(f"{ciphertext_int}:{election_id}".encode("utf-8"))

    recorded = vq.cast_vote_atomic(voter_id, election_id, str(ciphertext_int), transaction_hash)
    if not recorded:
        # Someone else's request for this same voter won the race.
        return {"success": False, "error": "You have already voted in this election."}

    return {"success": True, "transaction_hash": transaction_hash}


def tally_election(election_id: int) -> dict:
    """
    Decrypts and counts every vote for a closed election. Also verifies
    each vote's transaction hash before trusting it, and reports how many
    (if any) failed that check rather than silently dropping them.
    """
    election = q.get_election(election_id)
    if election is None:
        return {"success": False, "error": "Election not found."}
    if election["status"] != "closed":
        return {"success": False, "error": "Results can only be tallied after the election is closed."}

    private_key = _load_private_key(election)
    votes = vq.get_votes_for_election(election_id)

    results = {}  # position_id -> {candidate_id: count}
    tampered_count = 0

    for vote in votes:
        ciphertext_int = int(vote["encrypted_ballot"])
        expected_hash = sha256(f"{ciphertext_int}:{election_id}".encode("utf-8"))
        if expected_hash != vote["transaction_hash"]:
            tampered_count += 1
            continue

        plaintext = rsa_custom.decrypt_ballot(ciphertext_int, private_key)
        decoded = decode_ballot(plaintext)
        for position_id, candidate_id in decoded["selections"].items():
            results.setdefault(position_id, {})
            results[position_id][candidate_id] = results[position_id].get(candidate_id, 0) + 1

    return {
        "success": True,
        "results": results,
        "total_votes": len(votes),
        "tampered_detected": tampered_count,
    }
