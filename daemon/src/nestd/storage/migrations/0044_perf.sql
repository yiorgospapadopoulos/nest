-- Settings > Performance (B115). Each run measures some sections; `results` is JSON by
-- section id: its metrics, series, facts and error. Runs are kept until Clear old runs,
-- which keeps each section's two latest runs. A run still `running` at startup failed.
CREATE TABLE perf_runs (
    id TEXT PRIMARY KEY,
    -- JSON list of section ids, in the order they run.
    sections TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    -- running, done or failed
    state TEXT NOT NULL,
    error TEXT,
    version TEXT NOT NULL,
    git_commit TEXT,
    machine TEXT NOT NULL,
    results TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX perf_runs_started ON perf_runs (started_at);

-- Each daemon start, with how long it took from the process start to serving.
CREATE TABLE daemon_starts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ready_ms INTEGER NOT NULL,
    version TEXT NOT NULL,
    git_commit TEXT
);
CREATE INDEX daemon_starts_started ON daemon_starts (started_at);
