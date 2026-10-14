-- Pixies stage 3 (B41): harness tools by autonomy.
-- Limits on the chats a pixie starts: at once, and per local day.
ALTER TABLE pixies ADD COLUMN max_running INTEGER NOT NULL DEFAULT 2;
ALTER TABLE pixies ADD COLUMN max_per_day INTEGER NOT NULL DEFAULT 5;

-- The pixie that started a chat (no foreign key: the chat outlives the pixie), and the
-- batch of chats started in one of its turns, cleared once their report went back.
ALTER TABLE sessions ADD COLUMN started_by_pixie TEXT;
ALTER TABLE sessions ADD COLUMN pixie_batch TEXT;
CREATE INDEX sessions_started_by_pixie ON sessions (started_by_pixie);

-- Who a queued message comes from besides the user: the pixie that sent it, or the
-- daemon's report of finished chats to a pixie (`report_back`).
ALTER TABLE queued_messages ADD COLUMN from_pixie TEXT;
ALTER TABLE queued_messages ADD COLUMN origin TEXT;

-- What a pixie did through its harness tools; the latest 200 per pixie are kept.
CREATE TABLE pixie_activity (
    id INTEGER PRIMARY KEY,
    pixie_id TEXT NOT NULL REFERENCES pixies (id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    tool TEXT NOT NULL,
    session_id TEXT,
    summary TEXT NOT NULL
);
CREATE INDEX pixie_activity_pixie_id ON pixie_activity (pixie_id, id);
