-- The session's permission mode is Claude Code's own (its `defaultMode`) until the engine
-- reports it: the run opens without a mode (IMP-06).
ALTER TABLE sessions ADD COLUMN follows_claude_code_mode INTEGER NOT NULL DEFAULT 0;

-- The engine's id for each user message, the checkpoint its files can be restored to (IMP-02).
CREATE TABLE checkpoints (
    event_id INTEGER PRIMARY KEY REFERENCES events (id),
    session_id TEXT NOT NULL REFERENCES sessions (id),
    checkpoint_id TEXT NOT NULL
);
CREATE INDEX checkpoints_session_id ON checkpoints (session_id);
