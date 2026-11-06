-- Where new chats start in each project (B131): a branch, or a linked worktree with the
-- branch it is on. No row means the project folder. Named by project, like its config.
-- `gone` keeps a place that went away, under its last name, until clients have said so.
CREATE TABLE selected_places (
    repo TEXT PRIMARY KEY,
    branch TEXT NOT NULL,
    worktree_path TEXT,
    gone INTEGER NOT NULL DEFAULT 0
);
