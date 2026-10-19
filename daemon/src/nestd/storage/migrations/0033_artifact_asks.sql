-- Artifact pages ask Claude (B88, D118). Each call a page made, for its daily budget:
-- failed ones count too (`ok` 0, no tokens). Gone with the artifact.
CREATE TABLE artifact_asks (
    id INTEGER PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES artifacts (id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    ok INTEGER NOT NULL
);
CREATE INDEX artifact_asks_at ON artifact_asks (artifact_id, at);

-- Their tokens in Nest's usage totals, kept apart like the probes' (D031) and kept when the
-- artifact is deleted: the tokens were spent all the same.
CREATE TABLE ask_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_creation_input_tokens INTEGER NOT NULL,
    cache_read_input_tokens INTEGER NOT NULL
);
CREATE INDEX ask_usage_ts ON ask_usage (ts);
