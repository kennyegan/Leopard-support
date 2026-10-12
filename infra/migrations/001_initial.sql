CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS corpora (
 version text PRIMARY KEY, content_hash text NOT NULL, model text NOT NULL,
 permission jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS articles (
 id text NOT NULL, corpus_version text REFERENCES corpora(version), title text NOT NULL,
 category text NOT NULL, source_url text NOT NULL, is_synthetic boolean NOT NULL,
 allowed_visibility text NOT NULL, content_hash text NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(id, corpus_version)
);
CREATE TABLE IF NOT EXISTS sections (
 id text NOT NULL, corpus_version text NOT NULL, article_id text NOT NULL,
 heading text NOT NULL, section_text text NOT NULL, steps jsonb NOT NULL,
 embedding vector(384) NOT NULL, applicability jsonb NOT NULL,
 chunk_index integer NOT NULL, content_hash text NOT NULL,
 PRIMARY KEY(id, corpus_version), FOREIGN KEY(article_id, corpus_version) REFERENCES articles(id, corpus_version)
);
CREATE TABLE IF NOT EXISTS sessions (
 id uuid PRIMARY KEY, mode text NOT NULL CHECK(mode IN ('policy','baseline')),
 state jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS messages (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES sessions(id), role text NOT NULL,
 text_redacted text NOT NULL, response jsonb, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS state_snapshots (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES sessions(id),
 message_id uuid UNIQUE NOT NULL REFERENCES messages(id), state_json jsonb NOT NULL,
 interpretation jsonb NOT NULL, decision jsonb NOT NULL, retrieval jsonb NOT NULL,
 provider text NOT NULL, corpus_version text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS feedback (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES sessions(id),
 message_id uuid NOT NULL REFERENCES messages(id), state_snapshot_id uuid NOT NULL REFERENCES state_snapshots(id),
 kind text NOT NULL, value text NOT NULL, reason text NOT NULL, comment_redacted text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(message_id, kind)
);
CREATE TABLE IF NOT EXISTS tickets (
 id uuid PRIMARY KEY, session_id uuid UNIQUE NOT NULL REFERENCES sessions(id),
 draft_redacted text NOT NULL, edited boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS provider_usage (
 id integer PRIMARY KEY CHECK(id=1), calls integer NOT NULL DEFAULT 0
);
INSERT INTO provider_usage(id) VALUES(1) ON CONFLICT DO NOTHING;
CREATE OR REPLACE FUNCTION immutable_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Decision snapshots are immutable'; END; $$;
DROP TRIGGER IF EXISTS snapshot_immutable ON state_snapshots;
CREATE TRIGGER snapshot_immutable BEFORE UPDATE OR DELETE ON state_snapshots
FOR EACH ROW EXECUTE FUNCTION immutable_snapshot();
CREATE INDEX IF NOT EXISTS messages_session_idx ON messages(session_id, created_at);
