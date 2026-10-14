-- Claude Code session ids a session had before its conversation was cleared (/clear, B31).
-- Those transcripts stay the session's, so they are not listed as separate Claude Code chats.
CREATE TABLE earlier_provider_sessions (
    provider_session_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id)
);
CREATE INDEX earlier_provider_sessions_session_id ON earlier_provider_sessions (session_id);
