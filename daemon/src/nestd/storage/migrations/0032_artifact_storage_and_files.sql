-- Artifact pages that remember and carry files (B88, D117). What a page stores is kept per
-- artifact, shared by all its versions and the user's devices, until the artifact is
-- deleted. A version of an HTML page may carry files; their bytes are under
-- <data dir>/artifacts/<artifact id>/v<n>/ and these rows list them.
CREATE TABLE artifact_storage (
    artifact_id TEXT NOT NULL REFERENCES artifacts (id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (artifact_id, key)
);

CREATE TABLE artifact_files (
    artifact_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    path TEXT NOT NULL,
    -- Bytes of the file.
    size INTEGER NOT NULL,
    mime TEXT NOT NULL,
    PRIMARY KEY (artifact_id, version, path),
    FOREIGN KEY (artifact_id, version) REFERENCES artifact_versions (artifact_id, version)
        ON DELETE CASCADE
);
