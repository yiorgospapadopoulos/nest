-- B149: merge when checks pass, stacked pull requests and review guides, as JSON.
ALTER TABLE sessions ADD COLUMN merge_when_ready TEXT;
ALTER TABLE sessions ADD COLUMN stack TEXT;
ALTER TABLE sessions ADD COLUMN pr_guide TEXT;

-- A new approval kind, `restack`; SQLite cannot change a CHECK constraint in place.
CREATE TABLE approvals_new (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id),
    kind TEXT NOT NULL CHECK (
        kind IN ('permission', 'question', 'plan', 'review', 'merge', 'review_comments', 'restack')
    ),
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
