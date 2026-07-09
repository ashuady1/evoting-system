"""
services/anomaly_service.py

Feature engineering + Isolation Forest applied to login behavior.

Deliberately does NOT look at vote content (votes have no voter_id
attached at all — see schema.sql) — anomaly detection here is entirely
about *how* someone is logging in, not *what* they voted for. That
preserves anonymity while still catching bot-like or proxy-voting
patterns.

Three features per login event:
  1. otp_seconds_taken — time between password success and OTP entry.
     A human typing a 6-digit code takes a few seconds; near-zero times
     repeated across many accounts suggest a script, not a person.
  2. recent_attempts_by_voter — how many login attempts this voter has
     made in the preceding 5 minutes. Unusually high = something hammering
     one account.
  3. recent_attempts_by_device — how many login attempts have come from
     this exact device fingerprint in the preceding 5 minutes, across
     ANY voter. Unusually high = one machine trying many different
     accounts — a classic sign of credential stuffing or a bot farm,
     and something a per-account view alone would never catch.

SCALABILITY NOTE: recency counts are computed with a simple O(n^2) scan
over all login events, which is fine for a campus election's data volume
but would need proper indexed range queries at a larger scale — flagged
here rather than presented as production-ready.

KNOWN LIMITATION — "swamping": vanilla Isolation Forest isolates a
*single* outlier point very efficiently, but a *cluster* of several
similar anomalous points is genuinely harder — after the cluster splits
away from normal data as a group, more splits are still needed to
isolate individuals within it, which raises their average path length
(and lowers their anomaly score) compared to a lone outlier. This was
observed directly during testing: a simulated 8-10 event bot burst
scored with noticeably more overlap against normal logins than a smaller
3-5 event burst did. This is a documented characteristic of the
algorithm (see Liu et al.'s follow-up work on isolation-based methods),
not a bug in this implementation — see docs/DEVLOG.md for the measured
comparison. Mitigations for production use include extended/SCiForest
variants or supplementing with a separate rule (e.g. "flag N+ logins
from one device in five minutes") that catches large coordinated bursts
Isolation Forest alone may under-score.
"""

import json
import math
from datetime import datetime, timedelta

from database.db import get_connection, run_query
from security.isolation_forest import IsolationForest

RECENCY_WINDOW = timedelta(minutes=5)
NEUTRAL_OTP_TIME = 30.0  # used for events that never reached the OTP stage
MIN_SCORE_FLOOR = 0.55   # never flag anything below this, even if it's the local max
STD_DEV_MULTIPLIER = 1.0  # flag anything more than this many std-devs above the sample mean


def _parse_timestamp(value) -> datetime:
    """
    SQLite returns CURRENT_TIMESTAMP as a string ('2026-07-08 10:15:23');
    PostgreSQL (via psycopg2) returns it as a native datetime object
    already. Handle both so this works identically on either backend.
    """
    if isinstance(value, datetime):
        return value
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _fetch_all_login_events():
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM login_events ORDER BY attempted_at").fetchall()
    finally:
        conn.close()


def _build_feature_dataset():
    rows = _fetch_all_login_events()
    parsed = [
        {
            "id": r["id"],
            "voter_id": r["voter_id"],
            "device_hash": r["device_fingerprint_hash"],
            "timestamp": _parse_timestamp(r["attempted_at"]),
            "otp_seconds_taken": r["otp_seconds_taken"],
        }
        for r in rows
    ]

    window_seconds = RECENCY_WINDOW.total_seconds()

    def _within_window(a, b):
        return abs((a - b).total_seconds()) <= window_seconds

    features, meta = [], []
    for row in parsed:
        # Symmetric window (not "how many happened before this one") — a
        # burst of 5 near-simultaneous logins should score every one of
        # those 5 as part of a 5-event burst, not score them 1, 2, 3, 4, 5
        # depending on which happened to land first. A directional count
        # was tried first and happened to produce the intended burst
        # signal under SQLite, purely because SQLite's 1-second timestamp
        # precision made rapid-fire events look simultaneous — switching
        # to PostgreSQL (genuine microsecond precision) exposed that this
        # was accidental, not a real property of the feature. See
        # docs/DEVLOG.md for the direct comparison that caught this.
        recent_by_voter = sum(
            1 for other in parsed
            if other["voter_id"] == row["voter_id"] and _within_window(other["timestamp"], row["timestamp"])
        )
        recent_by_device = sum(
            1 for other in parsed
            if other["device_hash"] == row["device_hash"] and _within_window(other["timestamp"], row["timestamp"])
        )
        otp_time = row["otp_seconds_taken"] if row["otp_seconds_taken"] is not None else NEUTRAL_OTP_TIME

        features.append([otp_time, float(recent_by_voter), float(recent_by_device)])
        meta.append(row)

    return features, meta


def detect_anomalies(threshold: float = None, log_to_audit: bool = True) -> list:
    """
    Runs Isolation Forest over all login events and returns those flagged
    as anomalous, ranked highest-first.

    Threshold: rather than a single hardcoded cutoff (fragile — the right
    cutoff shifts with dataset size and how varied "normal" behavior is),
    we flag anything scoring more than STD_DEV_MULTIPLIER standard
    deviations above this batch's own mean score, with MIN_SCORE_FLOOR as
    an absolute safety floor so a perfectly uniform, boring batch doesn't
    get anomalies invented out of its own noise. Pass an explicit
    `threshold` to override this and use a fixed cutoff instead.
    """
    features, meta = _build_feature_dataset()
    if len(features) < 10:
        return []  # not enough history yet for a meaningful forest

    forest = IsolationForest(n_trees=300, subsample_size=min(256, len(features)))
    forest.fit(features)
    scores = forest.score_all(features)

    if threshold is None:
        mean_score = sum(scores) / len(scores)
        variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
        std_dev = math.sqrt(variance)
        threshold = max(MIN_SCORE_FLOOR, mean_score + STD_DEV_MULTIPLIER * std_dev)

    flagged = []
    for row, score, feature_vector in zip(meta, scores, features):
        if score >= threshold:
            flagged.append({
                "login_event_id": row["id"],
                "voter_id": row["voter_id"],
                "timestamp": row["timestamp"].isoformat(),
                "anomaly_score": round(score, 4),
                "otp_seconds_taken": feature_vector[0],
                "recent_attempts_by_voter": int(feature_vector[1]),
                "recent_attempts_by_device": int(feature_vector[2]),
            })

    flagged.sort(key=lambda entry: -entry["anomaly_score"])

    if log_to_audit:
        for entry in flagged:
            run_query(
                "INSERT INTO audit_log (event_type, details) VALUES (?, ?)",
                ("anomaly_flagged", json.dumps(entry)),
            )

    return flagged
