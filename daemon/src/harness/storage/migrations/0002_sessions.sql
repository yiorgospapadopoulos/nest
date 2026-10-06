CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    state TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('worktree', 'in_place')),
    cwd TEXT,
    worktree_path TEXT,
    branch TEXT,
    base_ref TEXT,
    model TEXT,
    effort TEXT,
    permission_mode TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_session_id TEXT,
    -- Set when the post-turn ref audit saw a change harness did not make (D013 layer 4).
    git_violation INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error TEXT
);

CREATE INDEX sessions_state ON sessions (state);

CREATE TABLE attachments (
    id TEXT PRIMARY KEY,
    -- NULL until the attachment is sent in a session.
    session_id TEXT REFERENCES sessions (id),
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX attachments_session_id ON attachments (session_id);
