-- Everything waiting on the user: permission prompts, agent questions and finished-work reviews.
CREATE TABLE approvals (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id),
    kind TEXT NOT NULL CHECK (kind IN ('permission', 'question', 'review')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'resolved', 'expired', 'superseded')),
    payload TEXT NOT NULL,
    resolution TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX approvals_status ON approvals (status);
CREATE INDEX approvals_session_id ON approvals (session_id);
