-- Each user message's file checkpoint as a git snapshot of the chat's folder (B145): the
-- commit under refs/nest/checkpoints/, taken in `folder` just before the agent had it.
CREATE TABLE file_snapshots (
    event_id INTEGER PRIMARY KEY REFERENCES events (id),
    session_id TEXT NOT NULL REFERENCES sessions (id),
    commit_sha TEXT NOT NULL,
    folder TEXT NOT NULL
);
CREATE INDEX file_snapshots_session_id ON file_snapshots (session_id);
