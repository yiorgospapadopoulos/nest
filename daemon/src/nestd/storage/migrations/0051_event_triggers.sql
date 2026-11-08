-- GitHub event triggers (B148). A habit's GitHub triggers, each with its filters.
ALTER TABLE pixie_habits ADD COLUMN github TEXT NOT NULL DEFAULT '[]';

-- The project trigger a chat was started by, and the event (JSON); NULL for other chats.
ALTER TABLE sessions ADD COLUMN started_by_trigger TEXT;

-- Since when each habit's or project trigger's GitHub events count, for its filters as
-- they are (`config`): an edit starts it again from then, so no older event fires.
CREATE TABLE trigger_watches (
    owner TEXT PRIMARY KEY,
    config TEXT NOT NULL,
    since TEXT NOT NULL
);

-- Each event a habit or project trigger took, once: what it did with it. Kept a week,
-- longer than an event stays in GitHub's lists that Nest reads.
CREATE TABLE trigger_events (
    owner TEXT NOT NULL,
    key TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT,
    session_id TEXT,
    PRIMARY KEY (owner, key)
);
CREATE INDEX trigger_events_at ON trigger_events (owner, at);
