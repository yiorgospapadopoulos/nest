-- Full-text search over session transcripts, session titles and Claude Code chat titles
-- (B13, D035). Filled from the events table by the search indexer.
CREATE VIRTUAL TABLE search_index USING fts5(
    text,
    -- title, user, assistant, tool, tool_result or claude_chat.
    kind UNINDEXED,
    -- A harness session id, or a Claude Code chat id for kind claude_chat.
    session_id UNINDEXED,
    -- Only for claude_chat rows; sessions are joined for theirs.
    repo UNINDEXED,
    -- The event the text came from; NULL for titles.
    event_id UNINDEXED,
    ts UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- The newest event id the indexer has read; 0 makes it index every stored event once.
CREATE TABLE search_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cursor INTEGER NOT NULL
);
INSERT INTO search_state (id, cursor) VALUES (1, 0);
