ALTER TABLE tickets ADD COLUMN IF NOT EXISTS problem_id text;
UPDATE sessions SET state=jsonb_set(state, '{problem_id}', to_jsonb(id::text)) WHERE NOT state ? 'problem_id';
UPDATE tickets SET problem_id=sessions.state->>'problem_id' FROM sessions WHERE tickets.session_id=sessions.id AND tickets.problem_id IS NULL;
ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_session_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS tickets_problem_key ON tickets(session_id,problem_id);
