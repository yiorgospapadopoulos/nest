-- What Claude Code reports about itself (D038): the model list and the signed-in account,
-- as JSON, so clients have them after a restart before the engine is asked again.
CREATE TABLE engine_info (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
