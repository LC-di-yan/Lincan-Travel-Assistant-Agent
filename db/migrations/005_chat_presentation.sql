-- Preserve existing text history and add an optional display projection.
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS presentation JSONB;
CREATE INDEX IF NOT EXISTS idx_chat_owner_session_order ON chat_messages(user_id, session_id, id DESC);
