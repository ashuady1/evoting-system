-- =====================================================================
-- E-VOTING SYSTEM — DATABASE SCHEMA (PostgreSQL variant)
-- =====================================================================
-- Mirrors schema.sql (SQLite) exactly in structure and intent — see that
-- file's comments for the design rationale (anonymity separation, etc).
-- The only differences here are PostgreSQL syntax: SERIAL instead of
-- INTEGER PRIMARY KEY AUTOINCREMENT, and TIMESTAMP instead of TEXT for
-- auto-generated audit columns.
-- =====================================================================

CREATE TABLE IF NOT EXISTS admins (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS authorized_voters (
    id SERIAL PRIMARY KEY,
    student_id_hash TEXT UNIQUE NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS voters (
    id SERIAL PRIMARY KEY,
    student_id_hash TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    totp_secret TEXT NOT NULL,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS elections (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    rsa_public_key TEXT,
    rsa_private_key TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    election_id INTEGER NOT NULL REFERENCES elections(id),
    title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
    id SERIAL PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(id),
    name TEXT NOT NULL,
    bio TEXT,
    photo_base64 TEXT,
    photo_mime TEXT
);

CREATE TABLE IF NOT EXISTS voter_election_status (
    voter_id INTEGER NOT NULL REFERENCES voters(id),
    election_id INTEGER NOT NULL REFERENCES elections(id),
    has_voted INTEGER NOT NULL DEFAULT 0,
    voted_at TIMESTAMP,
    PRIMARY KEY (voter_id, election_id)
);

CREATE TABLE IF NOT EXISTS votes (
    id SERIAL PRIMARY KEY,
    election_id INTEGER NOT NULL REFERENCES elections(id),
    encrypted_ballot TEXT NOT NULL,
    transaction_hash TEXT NOT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS login_events (
    id SERIAL PRIMARY KEY,
    voter_id INTEGER REFERENCES voters(id),
    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_hash TEXT,
    device_fingerprint_hash TEXT,
    success INTEGER NOT NULL,
    otp_seconds_taken REAL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    details TEXT,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
