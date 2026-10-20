-- Another engine's windows are kept by their length (B91): the free Codex plan has one
-- 30-day window. Codex's windows named by place before are dropped; Codex reports them
-- again with its next turn or refresh.
ALTER TABLE usage_limits ADD COLUMN minutes INTEGER;

DELETE FROM usage_limits WHERE provider != 'claude';
