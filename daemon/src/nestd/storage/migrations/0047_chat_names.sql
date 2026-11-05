-- True from a new chat's first moment until its name settles (B125): clients leave the name
-- blank meanwhile, and the engine's own replaces the quick one stored here. A name set by
-- hand or given when the chat was made never waits. Chats from before this keep theirs.
ALTER TABLE sessions ADD COLUMN title_pending INTEGER NOT NULL DEFAULT 0;
