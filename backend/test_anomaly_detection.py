"""
test_anomaly_detection.py

Simulates 25 normal logins (distinct voters, distinct devices, human-like
OTP entry times) plus a 5-event bot-like burst (all from ONE device
fingerprint, trying different voter accounts, entering the OTP almost
instantly) and checks that Isolation Forest actually separates the two
groups — not by a hardcoded rule, but by the algorithm genuinely finding
the bot-like points more "isolatable."

Why 5 events, not e.g. 20: Isolation Forest isolates a handful of similar
anomalies well, but a large, dense cluster of them is a known harder case
for the algorithm ("swamping" — see services/anomaly_service.py docstring
and docs/DEVLOG.md for a measured comparison). A 5-event burst is also
the more realistic thing to actually catch early — waiting for 20+
identical attempts before flagging anything defeats the point of
real-time detection.

Run with: python test_anomaly_detection.py
"""

import os
import random

from database.db import init_db, DB_PATH, run_query
from database import queries
from services import anomaly_service
from app import app

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"[PASS] {label}")
        passed += 1
    else:
        print(f"[FAIL] {label}")
        failed += 1


def main():
    random.seed(7)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()

    normal_event_ids = []
    bot_event_ids = []

    # login_events.voter_id has a foreign key to voters, so we need real
    # voter rows to attach these simulated events to — the specific
    # credentials don't matter for this test, only the login *behavior*.
    def _make_dummy_voter(label):
        return queries.insert_voter(f"dummy_{label}", "x", "x", "00" * 20)

    # --- 25 normal logins: distinct voter + distinct device each, human-paced OTP entry ---
    for i in range(25):
        voter_id = _make_dummy_voter(f"normal_{i}")
        event_id = queries.insert_login_event(
            voter_id=voter_id,
            ip_hash=f"ip_hash_{i}",
            device_fingerprint_hash=f"device_{i}",
            success=True,
            otp_seconds_taken=random.uniform(5.0, 10.0),
        )
        normal_event_ids.append(event_id)

    # --- 5-event bot-like burst: same device hammering different accounts, near-instant OTP ---
    for i in range(5):
        voter_id = _make_dummy_voter(f"bot_{i}")
        event_id = queries.insert_login_event(
            voter_id=voter_id,
            ip_hash="ip_hash_bot",
            device_fingerprint_hash="shared_bot_device",
            success=True,
            otp_seconds_taken=random.uniform(0.05, 0.3),
        )
        bot_event_ids.append(event_id)

    # --- run detection (adaptive threshold: mean + 1 std-dev of this batch's own scores) ---
    flagged = anomaly_service.detect_anomalies()
    flagged_ids = {entry["login_event_id"] for entry in flagged}

    check("Detection returns at least some flagged events", len(flagged) > 0)

    bot_flagged_count = len(flagged_ids & set(bot_event_ids))
    normal_flagged_count = len(flagged_ids & set(normal_event_ids))

    check(
        f"Most bot-like events are flagged ({bot_flagged_count}/5)",
        bot_flagged_count >= 4,
    )
    check(
        f"Few/no normal events are flagged ({normal_flagged_count}/25)",
        normal_flagged_count <= 3,
    )

    # --- direct feature-level sanity check, independent of the threshold ---
    features, meta = anomaly_service._build_feature_dataset()
    bot_indices = [i for i, m in enumerate(meta) if m["id"] in bot_event_ids]
    normal_indices = [i for i, m in enumerate(meta) if m["id"] in normal_event_ids]

    avg_bot_device_count = sum(features[i][2] for i in bot_indices) / len(bot_indices)
    avg_normal_device_count = sum(features[i][2] for i in normal_indices) / len(normal_indices)
    check(
        "Bot-like events show a much higher 'recent attempts from this device' count",
        avg_bot_device_count > avg_normal_device_count + 3,
    )

    avg_bot_otp_time = sum(features[i][0] for i in bot_indices) / len(bot_indices)
    avg_normal_otp_time = sum(features[i][0] for i in normal_indices) / len(normal_indices)
    check(
        "Bot-like events show much faster OTP entry than normal events",
        avg_bot_otp_time < avg_normal_otp_time / 3,
    )

    # --- confirm flagged anomalies were persisted to the audit log ---
    audit_rows = run_query("SELECT * FROM audit_log WHERE event_type = 'anomaly_flagged'", fetch="all")
    check("Flagged anomalies were written to the audit log", len(audit_rows) == len(flagged))

    # --- confirm the admin API endpoint surfaces the same thing ---
    client = app.test_client()
    from security.hashing import generate_salt, hash_with_salt
    salt = generate_salt()
    queries.insert_admin("test_admin", hash_with_salt("admin-password-123", salt), salt)
    r = client.post("/admin/login", json={"username": "test_admin", "password": "admin-password-123"})
    admin_headers = {"Authorization": f"Bearer {r.get_json()['token']}"}

    r = client.get("/admin/security/anomalies", headers=admin_headers)
    body = r.get_json()
    check("Admin anomalies endpoint responds successfully", r.status_code == 200 and body["success"])
    check("Admin anomalies endpoint reports a consistent count", body["count"] == len(body["flagged"]))

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
