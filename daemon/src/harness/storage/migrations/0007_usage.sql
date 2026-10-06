-- Tokens of each agent turn, for monthly totals and the usage calendar. No foreign key:
-- the rows outlive a deleted session, since the tokens were spent.
CREATE TABLE turn_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    repo TEXT NOT NULL,
    ts TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_creation_input_tokens INTEGER NOT NULL,
    cache_read_input_tokens INTEGER NOT NULL
);

CREATE INDEX turn_usage_ts ON turn_usage (ts);

-- The latest report of each subscription usage window (five_hour, seven_day).
CREATE TABLE usage_limits (
    name TEXT PRIMARY KEY,
    utilization REAL NOT NULL,
    resets_at TEXT,
    updated_at TEXT NOT NULL
);
