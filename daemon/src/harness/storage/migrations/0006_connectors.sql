-- The latest status of each MCP server and claude.ai connector, as Claude Code reported it
-- when a session's agent started. `source` is that session; it may since have been deleted.
CREATE TABLE connectors (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
