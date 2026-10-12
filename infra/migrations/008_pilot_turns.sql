CREATE TABLE IF NOT EXISTS pilot_turns (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 request_id uuid NOT NULL, input_hash text NOT NULL, state_revision bigint NOT NULL,
 status text NOT NULL CHECK(status IN ('processing','completed','uncertain','failed')),
 requires_inference boolean NOT NULL, lease_expires_at timestamptz NOT NULL,
 response jsonb, error_code text, elapsed_ms integer, provider text,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 UNIQUE(session_id,request_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS pilot_turns_active_session_idx ON pilot_turns(session_id) WHERE status='processing';
CREATE INDEX IF NOT EXISTS pilot_turns_lease_idx ON pilot_turns(lease_expires_at) WHERE status='processing';
ALTER TABLE pilot_turns ADD COLUMN IF NOT EXISTS usage jsonb NOT NULL DEFAULT '{}';
