-- A chat outlives its worktree (B119). `movable` marks the chats that work this way: those
-- created from now on, never a pixie's, a habit run's or a chat a pixie started. Nothing is
-- backfilled: earlier chats keep closing on merge and removing their worktree on delete.
-- `earlier_worktrees` is the JSON list of the worktrees the chat left, `moved_at` when it
-- last moved, `pending_worktree` the changes its tool recorded for the turn's end and
-- `worktree_note` what its agent hears with its next message about a change that failed.
ALTER TABLE sessions ADD COLUMN movable INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN earlier_worktrees TEXT NOT NULL DEFAULT '[]';
ALTER TABLE sessions ADD COLUMN moved_at TEXT;
ALTER TABLE sessions ADD COLUMN pending_worktree TEXT;
ALTER TABLE sessions ADD COLUMN worktree_note TEXT;
