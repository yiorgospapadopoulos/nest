-- Pixies on Codex (B91 stage 2): each pixie runs on an engine, Claude unless set to Codex.
-- Every earlier pixie is Claude's.
ALTER TABLE pixies ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude';

-- A pixie called from another chat while it or its caller runs on Codex runs as a session
-- of its own, linked to the calling chat here; NULL for every other session.
ALTER TABLE sessions ADD COLUMN called_by TEXT;
