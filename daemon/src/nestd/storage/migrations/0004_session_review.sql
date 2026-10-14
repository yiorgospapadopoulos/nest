-- Results of the daemon's git actions after the user approves a session's work.
ALTER TABLE sessions ADD COLUMN commit_sha TEXT;
ALTER TABLE sessions ADD COLUMN pr_url TEXT;
-- Tools the user allowed for the rest of the session ("always"), as a JSON list of names.
ALTER TABLE sessions ADD COLUMN allowed_tools TEXT NOT NULL DEFAULT '[]';
