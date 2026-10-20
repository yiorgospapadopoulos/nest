-- Usage per engine (B91): Claude and Codex turns count together in the calendar, and each
-- engine keeps its own usage windows. Every earlier row is Claude's.
ALTER TABLE turn_usage ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude';

CREATE TABLE engine_usage_limits (
    provider TEXT NOT NULL,
    name TEXT NOT NULL,
    utilization REAL NOT NULL,
    resets_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider, name)
);

INSERT INTO engine_usage_limits (provider, name, utilization, resets_at, updated_at)
    SELECT 'claude', name, utilization, resets_at, updated_at FROM usage_limits;

DROP TABLE usage_limits;

ALTER TABLE engine_usage_limits RENAME TO usage_limits;
