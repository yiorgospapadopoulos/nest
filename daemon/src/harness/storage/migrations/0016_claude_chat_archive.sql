-- Claude Code chats the user archived in harness (D040). Harness-only state: nothing is
-- written back to Claude Code. Keyed by Claude Code's session id.
CREATE TABLE claude_chat_archive (
    chat_id TEXT PRIMARY KEY,
    archived_at TEXT NOT NULL
);
