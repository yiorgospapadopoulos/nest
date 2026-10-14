CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    ts TEXT NOT NULL,
    session_id TEXT,
    payload TEXT NOT NULL
);

CREATE INDEX events_session_id ON events (session_id);

CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    is_local INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    revoked_at TEXT
);

-- At most one device represents this Mac.
CREATE UNIQUE INDEX devices_single_local ON devices (is_local) WHERE is_local = 1;

CREATE TABLE pairing_codes (
    code_hash TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
