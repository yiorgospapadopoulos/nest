-- Terminal agents use Nest (B151): the outside clients the user switched on, each with its
-- access level, and the client that started a chat.
CREATE TABLE outside_clients (
    kind TEXT PRIMARY KEY,
    access TEXT NOT NULL,
    turned_on_at TEXT NOT NULL,
    last_seen_at TEXT
);
ALTER TABLE sessions ADD COLUMN started_by_client TEXT;
