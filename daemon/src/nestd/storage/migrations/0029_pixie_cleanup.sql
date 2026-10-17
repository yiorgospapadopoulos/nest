-- Pixie details clean-up (B85, D109): every pixie works in every project, has no chat
-- backdrop and no tool rules of its own, and its reports reach the phone at the one level
-- of `[notifications] pixie_report_level`.
ALTER TABLE pixies DROP COLUMN projects;
ALTER TABLE pixies DROP COLUMN background;
ALTER TABLE pixies DROP COLUMN report_push;
ALTER TABLE pixies DROP COLUMN allowed_tools;
ALTER TABLE pixies DROP COLUMN disallowed_tools;
