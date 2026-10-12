-- Additive, repeatable migration; existing sessions and snapshots are preserved.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS request_id uuid;
CREATE UNIQUE INDEX IF NOT EXISTS messages_request_idx
    ON messages(session_id, request_id) WHERE request_id IS NOT NULL;
