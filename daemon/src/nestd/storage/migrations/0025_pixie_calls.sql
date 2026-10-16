-- The pixies each project chat called (B46): one row per Agent call of a pixie, and one
-- per SendMessage that continued it (`continues`: the tool use id of the agent's first
-- call, which its messages carry as their parent). `agent_id` is
-- Claude Code's id of the subagent, which a SendMessage names; `fingerprint` hashes the
-- pixie's subagent definition at the first call, so a changed pixie starts afresh.
-- `team_id` is the team it was called with; Send away sets `sent_away` on the pixie's
-- calls in that chat, so it leaves the chat's group and is no longer continued.
CREATE TABLE pixie_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    pixie_id TEXT NOT NULL REFERENCES pixies (id) ON DELETE CASCADE,
    team_id TEXT REFERENCES pixie_teams (id) ON DELETE SET NULL,
    tool_use_id TEXT NOT NULL,
    agent_id TEXT,
    continues TEXT,
    -- running, done, failed or interrupted
    state TEXT NOT NULL,
    -- Its tool call returned at once; it ends with its task (a SendMessage always does).
    background INTEGER NOT NULL DEFAULT 0,
    fingerprint TEXT NOT NULL,
    sent_away INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE (session_id, tool_use_id)
);
CREATE INDEX pixie_calls_agent ON pixie_calls (session_id, agent_id);
CREATE INDEX pixie_calls_state ON pixie_calls (state);
