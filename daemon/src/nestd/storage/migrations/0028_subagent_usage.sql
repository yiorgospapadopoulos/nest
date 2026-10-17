-- Subagent tokens (B84). A turn's result counts only the main chat, so each subagent API
-- reply is recorded too, once per message id: its streamed messages repeat the id, and the
-- latest counts replace the earlier ones. Main-chat rows keep `subagent` 0 and no id.
ALTER TABLE turn_usage ADD COLUMN subagent INTEGER NOT NULL DEFAULT 0;
ALTER TABLE turn_usage ADD COLUMN message_id TEXT;

CREATE UNIQUE INDEX turn_usage_message ON turn_usage (session_id, message_id)
    WHERE message_id IS NOT NULL;
