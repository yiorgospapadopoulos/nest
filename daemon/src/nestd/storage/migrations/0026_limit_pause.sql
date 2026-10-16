-- A chat paused at the subscription's usage limit (B78), as JSON ({window, resets_at,
-- resume_at, since}); NULL when not paused. The daemon goes on with it at `resume_at`.
ALTER TABLE sessions ADD COLUMN limit_pause TEXT;
