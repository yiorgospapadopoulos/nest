-- Ready-made artifact types (B88, D116): four new kinds, and who saved each version
-- (`user` for a document section the user edited in the reader).
--
-- SQLite cannot change a CHECK constraint in place, so both tables are rebuilt. Foreign
-- keys stay on while migrations run, and dropping `artifacts` would cascade into
-- `artifact_versions`; so the new versions table references the new artifacts table, the
-- old tables go in child-first order, and the renames carry the reference along. The two
-- triggers on `sessions` and `pixies` name `artifacts`, so they are dropped first and
-- recreated as they were; the indexes go with their table and are recreated too.
DROP TRIGGER artifacts_keep_chat_title;
DROP TRIGGER artifacts_keep_pixie_name;

CREATE TABLE artifacts_new (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN ('markdown', 'html', 'slides', 'document', 'design', 'design_system')
    ),
    repo TEXT NOT NULL,
    session_id TEXT,
    chat_title TEXT,
    pixie_id TEXT,
    pixie_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    seen_at TEXT
);
INSERT INTO artifacts_new (id, title, kind, repo, session_id, chat_title, pixie_id,
    pixie_name, created_at, updated_at, seen_at)
SELECT id, title, kind, repo, session_id, chat_title, pixie_id, pixie_name, created_at,
    updated_at, seen_at FROM artifacts ORDER BY rowid;

CREATE TABLE artifact_versions_new (
    artifact_id TEXT NOT NULL REFERENCES artifacts_new (id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    title TEXT NOT NULL,
    -- Bytes of the version's UTF-8 content.
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT 'agent' CHECK (author IN ('agent', 'user')),
    PRIMARY KEY (artifact_id, version)
);
INSERT INTO artifact_versions_new (artifact_id, version, title, size, created_at)
SELECT artifact_id, version, title, size, created_at FROM artifact_versions ORDER BY rowid;

DROP TABLE artifact_versions;
DROP TABLE artifacts;
ALTER TABLE artifacts_new RENAME TO artifacts;
ALTER TABLE artifact_versions_new RENAME TO artifact_versions;

CREATE INDEX artifacts_updated ON artifacts (updated_at);
CREATE INDEX artifacts_session ON artifacts (session_id);
CREATE INDEX artifacts_pixie ON artifacts (pixie_id);

CREATE TRIGGER artifacts_keep_chat_title BEFORE DELETE ON sessions
BEGIN
    UPDATE artifacts SET chat_title = OLD.title WHERE session_id = OLD.id;
END;

CREATE TRIGGER artifacts_keep_pixie_name BEFORE DELETE ON pixies
BEGIN
    UPDATE artifacts SET pixie_name = OLD.name WHERE pixie_id = OLD.id;
END;
