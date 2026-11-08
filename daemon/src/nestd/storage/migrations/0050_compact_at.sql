-- How many tokens a chat, or a pixie's chats, hold before the engine compacts by itself
-- (B146). NULL leaves it to the engine, as before.
ALTER TABLE sessions ADD COLUMN compact_at INTEGER;
ALTER TABLE pixies ADD COLUMN compact_at INTEGER;
