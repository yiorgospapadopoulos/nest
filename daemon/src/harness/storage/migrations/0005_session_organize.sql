-- Chat management: pinned sessions list first; archived ones leave the default list.
ALTER TABLE sessions ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN archived_at TEXT;
