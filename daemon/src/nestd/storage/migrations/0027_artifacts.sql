-- Artifacts (B79): Markdown documents and small HTML pages a chat or pixie saved. Each
-- version's content is a file under <data dir>/artifacts/<artifact id>/; these rows hold
-- the history. No foreign keys to the chat or the pixie: an artifact outlives both, and
-- keeps their names in `chat_title` and `pixie_name` (filled by the triggers below).
-- `seen_at` is NULL until the user opens its latest version.
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('markdown', 'html')),
    repo TEXT NOT NULL,
    session_id TEXT,
    chat_title TEXT,
    pixie_id TEXT,
    pixie_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    seen_at TEXT
);
CREATE INDEX artifacts_updated ON artifacts (updated_at);
CREATE INDEX artifacts_session ON artifacts (session_id);
CREATE INDEX artifacts_pixie ON artifacts (pixie_id);

CREATE TABLE artifact_versions (
    artifact_id TEXT NOT NULL REFERENCES artifacts (id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    title TEXT NOT NULL,
    -- Bytes of the version's UTF-8 content.
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (artifact_id, version)
);

CREATE TRIGGER artifacts_keep_chat_title BEFORE DELETE ON sessions
BEGIN
    UPDATE artifacts SET chat_title = OLD.title WHERE session_id = OLD.id;
END;

CREATE TRIGGER artifacts_keep_pixie_name BEFORE DELETE ON pixies
BEGIN
    UPDATE artifacts SET pixie_name = OLD.name WHERE pixie_id = OLD.id;
END;
