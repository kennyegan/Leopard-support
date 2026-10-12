CREATE TABLE IF NOT EXISTS pilot_invites (
 email text PRIMARY KEY CHECK(email=lower(email)), role text NOT NULL CHECK(role IN ('tester','admin')),
 active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS pilot_users (
 id uuid PRIMARY KEY, issuer text NOT NULL, subject text NOT NULL, email text NOT NULL UNIQUE REFERENCES pilot_invites(email),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(issuer,subject)
);
CREATE TABLE IF NOT EXISTS pilot_logins (
 token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES pilot_users(id), csrf_token text NOT NULL,
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pilot_logins_expiry_idx ON pilot_logins(expires_at);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS owner_id uuid REFERENCES pilot_users(id);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS revision bigint NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS sessions_owner_idx ON sessions(owner_id, updated_at);
CREATE TABLE IF NOT EXISTS pilot_rate_windows (
 key text NOT NULL, window_start bigint NOT NULL, count integer NOT NULL DEFAULT 0,
 expires_at timestamptz NOT NULL, PRIMARY KEY(key,window_start)
);
CREATE TABLE IF NOT EXISTS pilot_audit (
 id bigserial PRIMARY KEY, event text NOT NULL, actor_id uuid, object_id uuid,
 metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pilot_audit_created_idx ON pilot_audit(created_at);
