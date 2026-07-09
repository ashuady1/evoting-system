# E-Voting System — Setup & Run Guide

## First-time setup

```bash
cd evoting-system/backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Initialize the database (run once, and again anytime you want a clean slate)

```bash
python database/db.py
```

You should see: `Database initialized at .../evoting.db`

## Run the whole thing (server + frontend)

**If you set up the project before candidate photos were added:** delete
`backend/database/evoting.db` first — SQLite doesn't auto-add new
columns to an existing table, so the old database won't have the photo
fields the candidate form now sends.

```bash
python database/db.py      # if you haven't already
python create_admin.py     # create your admin login (do this once)
python app.py               # starts the server on :5000
```

Then open in your browser:
- **Voter portal:** http://127.0.0.1:5000/
- **Admin dashboard:** http://127.0.0.1:5000/admin

**You need an internet connection for the pages to look right.** The
frontend loads Tailwind CSS, Google Fonts, Lucide icons, and flatpickr
from CDNs rather than bundling them — a deliberate trade-off for visual
polish (see docs/DEVLOG.md Entry 16). If you're presenting somewhere
with unreliable wifi, test the connection at the venue beforehand or
bring a mobile hotspot as backup.

Sign in to the admin dashboard with the account you just created, paste
in a few student IDs under "Authorized voters," create an election, add
positions and candidates, open it — then switch to the voter portal in
another tab (or a private/incognito window, since both use the same
browser's localStorage for their separate session tokens) and register +
vote as one of those student IDs.

You can also hit `http://127.0.0.1:5000/health` directly for a quick
JSON check that Flask and the database are both up.

## Deploying this for real (a live URL, not just localhost)

See **`DEPLOYMENT.md`** for a complete, free-tier-only walkthrough
(Neon for PostgreSQL + Render for hosting — $0, no credit card anywhere).
The database layer now supports both SQLite (local dev, unchanged) and
PostgreSQL (production, via a `DATABASE_URL` environment variable) — see
`docs/DEVLOG.md` Entry 17 for what that involved and a real bug it caught
along the way.

## What exists so far

- `database/schema.sql` — full database design (voters, elections,
  positions, candidates, votes, audit log)
- `database/schema_postgres.sql` — same schema for PostgreSQL (production)
- `database/db.py` / `database/queries.py` — connection handling and all
  parameterized queries; supports SQLite and PostgreSQL behind one interface
- `security/hashing.py` — SHA-256 from scratch, validated against `hashlib`
- `security/hmac_custom.py` — HMAC-SHA256 from scratch, validated against Python's `hmac` module
- `security/totp.py` — TOTP from scratch, validated against official RFC 6238 test vectors
- `security/tokens.py` — signed session tokens built on our own HMAC
- `security/config_secrets.py` — auto-generates and persists the server signing key and ID-hashing pepper on first run
- `services/auth_service.py` — registration + two-step login business logic
- `routes/voter_routes.py`, `routes/admin_routes.py` — Flask endpoints
- `create_admin.py` — CLI to bootstrap the first admin account
- `test_auth_flow.py` — end-to-end test of the full auth flow (13 checks)
- `services/election_service.py`, `database/queries_elections.py` — election/position/candidate management, draft-lock business rules, draft-only editing, turnout stats
- `test_election_flow.py` — end-to-end test of election setup, the "2+ candidates before opening" rule, and session-gated ballot viewing (13 checks)
- `test_election_editing_and_turnout.py` — draft-only editing rules + turnout math (12 checks)
- `security/rsa_custom.py` — RSA from scratch (modular exponentiation, extended Euclidean algorithm, Miller-Rabin primality test, padded ballot encryption), 2048-bit keys
- `services/ballot_service.py`, `database/queries_votes.py` — ballot encoding/validation/encryption, race-safe one-vote enforcement, results tallying with tamper detection
- `test_ballot_flow.py` — end-to-end test: cast votes, block double-voting, detect a tampered record, verify correct tally (19 checks)
- `security/isolation_forest.py` — Isolation Forest from scratch, validated on synthetic outliers
- `services/anomaly_service.py` — login behavior feature extraction + adaptive-threshold anomaly flagging
- `test_anomaly_detection.py` — simulates normal vs. bot-like login behavior and confirms detection (8 checks)
- `frontend/` — voter portal (`index.html`) and admin dashboard (`admin.html`), built with Tailwind CSS, Google Fonts, Lucide icons, and flatpickr (all via CDN — see the internet-connection note above), served directly by Flask
- `routes/dev_routes.py` — **demo-only** OTP auto-fill endpoint (see docs/DEVLOG.md Entry 12 — must be removed before any real deployment)
- `test_full_demo_flow.py` — replays the entire presentation script end-to-end through every API call the UI makes (17 checks)

### Try the whole auth flow yourself (command line, no browser needed)

```bash
python test_auth_flow.py
```

This resets a throwaway database, then runs through: unauthorized ID
rejected → admin adds the ID → registration succeeds → duplicate
registration rejected → wrong password rejected → correct password
accepted → wrong OTP rejected → correct OTP accepted, session issued →
admin login → protected voter-upload endpoint.

## What's next (in build order)

1. ~~Password + student ID hashing module (SHA-256 from scratch)~~ ✅
2. ~~Admin: upload authorized voter list, create elections/positions/candidates~~ ✅
3. ~~Voter registration + login (password + TOTP)~~ ✅
4. ~~RSA module (key generation via Miller-Rabin, padded encryption)~~ ✅
5. ~~Ballot casting (multi-position, one-vote-per-election enforcement)~~ ✅
6. ~~Isolation Forest anomaly detection on login behavior~~ ✅
7. ~~Admin dashboard UI + voter portal frontend~~ ✅
8. ~~UI overhaul: Tailwind/fonts/icons/flatpickr, home dashboard, election editing~~ ✅
9. Polish pass / anything you want to add before the presentation (see docs/DEVLOG.md "Milestones checklist")

### Run all six test suites

```bash
python test_auth_flow.py
python test_election_flow.py
python test_election_editing_and_turnout.py
python test_ballot_flow.py
python test_anomaly_detection.py
python test_full_demo_flow.py
```

Each resets the database at the start, so they're safe to re-run in any
order. `test_full_demo_flow.py` is the one that mirrors an actual live
demo end-to-end — good one to run the morning of your presentation.

See `docs/DEVLOG.md` for the reasoning behind every decision made along the
way — that file is what you'll turn into your report's implementation
chapter.
