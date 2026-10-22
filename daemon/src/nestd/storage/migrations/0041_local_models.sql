-- B106: local models. A server is one address speaking an OpenAI- or Anthropic-style API;
-- which of the three APIs it answers decides whether the engines reach it directly or
-- through Nest's translator. An optional key lives in the Keychain; `has_key` says one is
-- there.
CREATE TABLE local_servers (
    id TEXT PRIMARY KEY,
    address TEXT NOT NULL UNIQUE,
    base_url TEXT NOT NULL,
    app TEXT,
    has_messages INTEGER NOT NULL,
    has_responses INTEGER NOT NULL,
    has_chat INTEGER NOT NULL,
    has_key INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT NOT NULL
);

CREATE TABLE local_models (
    id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL REFERENCES local_servers (id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    name TEXT NOT NULL,
    context INTEGER,
    tools TEXT NOT NULL CHECK (tools IN ('good', 'weak', 'none', 'unknown')),
    weak_reason TEXT,
    vision INTEGER NOT NULL,
    thinking INTEGER NOT NULL,
    -- Bytes on disk, when the server said, for the memory warning.
    size_bytes INTEGER,
    position INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE (server_id, model)
);

-- Tokens local turns used, by local day; never a cost.
CREATE TABLE local_usage (
    day TEXT NOT NULL,
    model_id TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    PRIMARY KEY (day, model_id)
);

-- `local_engine`, `local_only` and `first_run_done`, as JSON values.
CREATE TABLE local_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
