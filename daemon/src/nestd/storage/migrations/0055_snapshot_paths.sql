-- The paths the chat's own turns changed after each file checkpoint, as a JSON list, so a
-- rewind restores only those (B159 R10). NULL when not known, as for older checkpoints:
-- their rewind restores the whole folder.
ALTER TABLE file_snapshots ADD COLUMN paths TEXT;
-- Where a running turn's work is measured from, as JSON ({"commit", "folder", "first"}),
-- on the checkpoint it counts for; NULL once the turn's paths are recorded. Kept here, not
-- in memory, so a turn cut off by a restart still gets its paths when Nest starts again.
ALTER TABLE file_snapshots ADD COLUMN turn_mark TEXT;
