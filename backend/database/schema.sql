-- =====================================================================
-- E-VOTING SYSTEM — DATABASE SCHEMA
-- =====================================================================
-- Design principle: the table that proves WHO VOTED and the table that
-- stores WHAT WAS VOTED are completely separate, with no foreign key
-- between them. This is the core anonymity mechanism: even someone with
-- full database access can see "voter #42 has voted" and can see
-- "one ballot said X" but cannot join the two. Anonymity here comes
-- from the schema design, not just from encryption.
-- =====================================================================

-- Admins who configure elections and view audit logs.
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,   -- SHA-256(password + salt), computed in code
    salt TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Pre-loaded by an admin BEFORE anyone can register. Only a student ID
-- whose hash appears here is allowed to create an account. This is what
-- stops a random person from just inventing an ID and registering.
--
-- email_hash: added to close a real gap — knowing a student ID alone
-- (often not very secret: printed on ID cards, class rosters) used to be
-- enough to register AS that student. Registration now also requires
-- proving access to the matching official email via a sent verification
-- code (see services/auth_service.py). Nullable for backward
-- compatibility with any authorized_voters row added before this
-- feature existed — see database/migrate_add_email_hash.py.
CREATE TABLE IF NOT EXISTS authorized_voters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id_hash TEXT UNIQUE NOT NULL,   -- SHA-256(student_id + system_salt)
    email_hash TEXT,                        -- SHA-256(normalized_email + system_salt)
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Created when a pre-authorized student registers. Holds everything
-- needed to authenticate them, but nothing that identifies how they voted.
CREATE TABLE IF NOT EXISTS voters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id_hash TEXT UNIQUE NOT NULL,  -- must exist in authorized_voters
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    totp_secret TEXT NOT NULL,             -- per-voter secret for time-based OTP
    registered_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- One election can have multiple positions (President, VP, Secretary...).
CREATE TABLE IF NOT EXISTS elections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',   -- draft | open | closed
    rsa_public_key TEXT,                    -- (n, e) generated per election
    rsa_private_key TEXT,                   -- (n, d) — see docs/DEVLOG.md re: key custody
    results_published INTEGER NOT NULL DEFAULT 0,  -- admin must explicitly publish before voters see results
    published_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    election_id INTEGER NOT NULL REFERENCES elections(id),
    title TEXT NOT NULL   -- e.g. "President", "General Secretary"
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL REFERENCES positions(id),
    name TEXT NOT NULL,
    bio TEXT,
    photo_base64 TEXT,   -- optional candidate photo, resized client-side before upload
    photo_mime TEXT      -- e.g. 'image/jpeg' — needed to reconstruct a data URI
);

-- Tracks ONLY whether a voter has voted in a given election — nothing
-- about their choices. This table is what enforces one-vote-per-election.
CREATE TABLE IF NOT EXISTS voter_election_status (
    voter_id INTEGER NOT NULL REFERENCES voters(id),
    election_id INTEGER NOT NULL REFERENCES elections(id),
    has_voted INTEGER NOT NULL DEFAULT 0,   -- 0/1 boolean
    voted_at TEXT,
    PRIMARY KEY (voter_id, election_id)
);

-- The actual ballots. Deliberately has NO voter_id column.
-- One row = one encrypted ballot for one election. Nothing links it
-- back to voter_election_status.
CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    election_id INTEGER NOT NULL REFERENCES elections(id),
    encrypted_ballot TEXT NOT NULL,     -- RSA-encrypted, padded blob (all positions)
    transaction_hash TEXT NOT NULL,     -- SHA-256 seal — detects tampering
    submitted_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Every login attempt, success or failure — this is the raw material
-- the anomaly detector (Isolation Forest) will run on later.
CREATE TABLE IF NOT EXISTS login_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voter_id INTEGER REFERENCES voters(id),
    attempted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    ip_hash TEXT,
    device_fingerprint_hash TEXT,
    success INTEGER NOT NULL,           -- 0/1
    otp_seconds_taken REAL              -- time between OTP shown and submitted
);

-- General-purpose audit trail: flagged anomalies, admin actions, etc.
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,           -- e.g. 'anomaly_flagged', 'election_opened'
    details TEXT,
    logged_at TEXT DEFAULT CURRENT_TIMESTAMP
);
