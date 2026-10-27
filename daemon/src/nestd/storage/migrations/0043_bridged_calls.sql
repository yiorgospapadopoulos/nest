-- Pixie calls made with Nest's call_pixie tool (B112): one row per call, linking the
-- calling chat's tool call to the called pixie's own session. Calling the same pixie
-- again in the chat continues that session (`root`: the tool use id of the first call of
-- the chain) while `fingerprint`, which hashes the pixie's definition, is unchanged and
-- it was not sent away. `delivered` marks a background call whose result reached the
-- caller. On a restart, calls still `running` become `interrupted`.
CREATE TABLE pixie_bridged_calls (
    caller TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    tool_use_id TEXT NOT NULL,
    pixie_id TEXT NOT NULL REFERENCES pixies (id) ON DELETE CASCADE,
    called TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    root TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    background INTEGER NOT NULL,
    -- running, done, failed, stopped or interrupted
    state TEXT NOT NULL,
    sent_away INTEGER NOT NULL DEFAULT 0,
    delivered INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    PRIMARY KEY (caller, tool_use_id)
);
CREATE INDEX pixie_bridged_calls_pixie ON pixie_bridged_calls (caller, pixie_id);
CREATE INDEX pixie_bridged_calls_state ON pixie_bridged_calls (state);
