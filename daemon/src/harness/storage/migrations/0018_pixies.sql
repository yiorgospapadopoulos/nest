-- Pixies: saved agents with their own soul, memory and chat (B34, D057).
CREATE TABLE pixies (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    mascot TEXT NOT NULL,
    color TEXT NOT NULL,
    background TEXT NOT NULL,
    model TEXT,
    effort TEXT,
    permission_mode TEXT NOT NULL,
    autonomy TEXT NOT NULL,
    project_access TEXT NOT NULL,
    -- JSON list of repo names; NULL means every project.
    projects TEXT,
    -- JSON lists: Claude Code skill names (empty: all), ids of pixies this one may call,
    -- and permission rules for tools that never prompt or are never available.
    skills TEXT NOT NULL,
    can_call TEXT NOT NULL,
    allowed_tools TEXT NOT NULL DEFAULT '[]',
    disallowed_tools TEXT NOT NULL DEFAULT '[]',
    hidden INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL,
    -- The pixie's current chat; NULL until the first message or after a reset.
    chat_session_id TEXT REFERENCES sessions (id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- A pixie's chats are sessions marked with the pixie; project lists leave them out.
ALTER TABLE sessions ADD COLUMN pixie_id TEXT REFERENCES pixies (id);
CREATE INDEX sessions_pixie_id ON sessions (pixie_id);
