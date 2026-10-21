-- B101: GitHub issues become chats; pull request review comments go back to the agent.

-- The issue a chat started from, and its pull request's review comments, as JSON.
ALTER TABLE sessions ADD COLUMN issue TEXT;
ALTER TABLE sessions ADD COLUMN review TEXT;
-- What a queued message's event adds for clients, such as the review comments Nest sent.
ALTER TABLE queued_messages ADD COLUMN extra TEXT;

-- A new approval kind, `review_comments`; SQLite cannot change a CHECK constraint in place.
CREATE TABLE approvals_new (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id),
    kind TEXT NOT NULL CHECK (
        kind IN ('permission', 'question', 'plan', 'review', 'merge', 'review_comments')
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
