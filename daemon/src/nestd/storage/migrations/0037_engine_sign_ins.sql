-- B94: which engine Nest first saw signed in; new chats default to that engine's model.
CREATE TABLE engine_sign_ins (
    provider TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL
);

-- An install from before B94 signed in to Claude counts Claude as first, from when its
-- account was last reported.
INSERT INTO engine_sign_ins (provider, first_seen_at)
SELECT 'claude', updated_at FROM engine_info
WHERE name = 'account' AND json_extract(data, '$.plan') IS NOT NULL;

-- A pixie on its engine's default entry gets the concrete model when the daemon starts.
UPDATE pixies SET model = NULL WHERE model = 'default';
