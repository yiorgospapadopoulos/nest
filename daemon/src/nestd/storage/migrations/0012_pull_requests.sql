-- Pull request status, merge approvals and short summaries (B12, D034).

-- A new approval kind, `merge`; SQLite cannot change a CHECK constraint in place.
CREATE TABLE approvals_new (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id),
    kind TEXT NOT NULL CHECK (kind IN ('permission', 'question', 'plan', 'review', 'merge')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'resolved', 'expired', 'superseded')),
    payload TEXT NOT NULL,
    resolution TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
INSERT INTO approvals_new SELECT id, session_id, kind, status, payload, resolution, created_at,
    resolved_at FROM approvals;
DROP TABLE approvals;
ALTER TABLE approvals_new RENAME TO approvals;
CREATE INDEX approvals_status ON approvals (status);
CREATE INDEX approvals_session_id ON approvals (session_id);

-- The pull request's last known status on GitHub, as JSON.
ALTER TABLE sessions ADD COLUMN pr TEXT;
-- Up to three lines describing the pull request harness opened.
ALTER TABLE sessions ADD COLUMN pr_summary TEXT;
