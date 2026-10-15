-- A message sent while a turn runs is written into the running turn, where Claude Code
-- reads it at its next step; it stays here, marked sent, until Claude Code echoes it (B59).
ALTER TABLE queued_messages ADD COLUMN sent INTEGER NOT NULL DEFAULT 0;

-- A rewound or forked conversation waiting for its next run: that run resumes `fork_from`
-- only up to the entry `fork_at`, into a new Claude Code session; `fork_drops` is the user
-- message whose turn the cut drops, when only that turn goes (B59).
ALTER TABLE sessions ADD COLUMN fork_from TEXT;
ALTER TABLE sessions ADD COLUMN fork_at TEXT;
ALTER TABLE sessions ADD COLUMN fork_drops TEXT;
