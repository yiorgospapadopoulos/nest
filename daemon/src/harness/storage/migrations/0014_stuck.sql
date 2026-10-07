-- Stuck detection (B14, D036).

-- Why the session looks stuck right now, as JSON ({reason, since, details}); NULL when not.
ALTER TABLE sessions ADD COLUMN stuck TEXT;
-- A message that interrupted the turn (a nudge) runs before the rest of the queue.
ALTER TABLE queued_messages ADD COLUMN urgent INTEGER NOT NULL DEFAULT 0;
