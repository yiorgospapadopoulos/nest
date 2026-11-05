-- Autopilot (a chat that works on without the user): the run in progress, as JSON; NULL when
-- there is none. A habit can run on Autopilot.
ALTER TABLE sessions ADD COLUMN autopilot TEXT;
ALTER TABLE pixie_habits ADD COLUMN autopilot INTEGER NOT NULL DEFAULT 0;
