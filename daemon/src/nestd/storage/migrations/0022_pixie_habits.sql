-- Pixies stage 4 (B42): habits, their runs, and reports.

-- A pixie's habit: a prompt it runs in the background on a schedule (JSON, local time of
-- the Mac) or on events (a JSON list of trigger names), or both.
CREATE TABLE pixie_habits (
    id TEXT PRIMARY KEY,
    pixie_id TEXT NOT NULL REFERENCES pixies (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    schedule TEXT,
    triggers TEXT NOT NULL DEFAULT '[]',
    max_minutes INTEGER NOT NULL DEFAULT 20,
    enabled INTEGER NOT NULL DEFAULT 1,
    -- The scheduled times up to here are handled: queued, or before the habit was created,
    -- rescheduled or resumed.
    scheduled_through TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX pixie_habits_pixie_id ON pixie_habits (pixie_id, created_at);

-- One run of a habit, from queued to its outcome; the latest 20 finished ones per habit
-- are kept. `kind` is schedule, trigger or manual (Run now).
CREATE TABLE pixie_habit_runs (
    id TEXT PRIMARY KEY,
    habit_id TEXT NOT NULL REFERENCES pixie_habits (id) ON DELETE CASCADE,
    pixie_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    session_id TEXT,
    due_at TEXT,
    started_at TEXT,
    ended_at TEXT,
    outcome TEXT NOT NULL,
    reason TEXT,
    report_title TEXT,
    -- JSON list of the events a triggered run was started for.
    trigger_events TEXT
);
CREATE INDEX pixie_habit_runs_habit_id ON pixie_habit_runs (habit_id);
CREATE INDEX pixie_habit_runs_outcome ON pixie_habit_runs (outcome, due_at);

-- What a pixie reported through its `report` tool, from its chat or a habit run.
CREATE TABLE pixie_reports (
    id TEXT PRIMARY KEY,
    pixie_id TEXT NOT NULL REFERENCES pixies (id) ON DELETE CASCADE,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    link TEXT,
    -- The habit and run it came from, if any; the name as it was then.
    habit_id TEXT,
    habit_name TEXT,
    run_id TEXT,
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX pixie_reports_pixie_id ON pixie_reports (pixie_id, read_at);
CREATE INDEX pixie_reports_created_at ON pixie_reports (created_at);

-- The lowest severity of a pixie's reports that reaches the phone: action, warn or info.
ALTER TABLE pixies ADD COLUMN report_push TEXT NOT NULL DEFAULT 'action';

-- A habit run's session: it carries the pixie's id but is not its chat.
ALTER TABLE sessions ADD COLUMN habit_run_id TEXT;
