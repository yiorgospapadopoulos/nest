-- Tokens of the usage probes (D031): harness overhead, kept apart from the user's turns so
-- month totals and session counts only show the user's own work.
CREATE TABLE probe_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_creation_input_tokens INTEGER NOT NULL,
    cache_read_input_tokens INTEGER NOT NULL
);

CREATE INDEX probe_usage_ts ON probe_usage (ts);
