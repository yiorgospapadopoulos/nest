-- Why a connector failed, as Claude Code reported it.
ALTER TABLE connectors ADD COLUMN error TEXT;
