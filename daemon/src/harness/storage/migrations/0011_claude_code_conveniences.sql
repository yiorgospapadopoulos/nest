-- Claude Code conveniences (D032): plan approvals, the context meter, slash command lists
-- and queued follow-up messages.

-- A new approval kind, `plan`; SQLite cannot change a CHECK constraint in place.
CREATE TABLE approvals_new (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id),
    kind TEXT NOT NULL CHECK (kind IN ('permission', 'question', 'plan', 'review')),
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

-- How full the agent's context window was after its last turn, as JSON.
ALTER TABLE sessions ADD COLUMN context TEXT;

-- The last slash commands and agents an agent run reported, per session and per repo, as JSON.
CREATE TABLE command_catalogs (
    scope TEXT NOT NULL CHECK (scope IN ('session', 'repo')),
    key TEXT NOT NULL,
    catalog TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);

-- Messages sent while a turn runs, delivered one per turn in order.
CREATE TABLE queued_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id),
    text TEXT NOT NULL,
    -- Summaries of the message's attachments (id, filename, media_type, size), as JSON.
    attachments TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX queued_messages_session_id ON queued_messages (session_id);
