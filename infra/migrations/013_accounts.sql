-- Optional sign-in for the public demo. Only the identity provider's stable subject is kept;
-- email addresses and phone numbers stay with the provider.
CREATE TABLE IF NOT EXISTS accounts (
 id uuid PRIMARY KEY, issuer text NOT NULL, subject text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), last_seen_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(issuer, subject)
);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS account_id uuid REFERENCES accounts(id);
CREATE INDEX IF NOT EXISTS sessions_account_idx ON sessions(account_id, updated_at DESC);

CREATE OR REPLACE FUNCTION purge_account_session(target uuid, expected_account uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 PERFORM 1 FROM public.sessions WHERE id=target AND account_id=expected_account FOR UPDATE;
 IF NOT FOUND OR expected_account IS NULL THEN RETURN false; END IF;
 INSERT INTO public.pilot_deletion_authorizations VALUES(target,txid_current());
 DELETE FROM public.feedback WHERE session_id=target;
 DELETE FROM public.tickets WHERE session_id=target;
 DELETE FROM public.state_snapshots WHERE session_id=target;
 DELETE FROM public.messages WHERE session_id=target;
 DELETE FROM public.sessions WHERE id=target;
 DELETE FROM public.pilot_deletion_authorizations WHERE session_id=target;
 RETURN true;
END; $$;
REVOKE ALL ON FUNCTION purge_account_session(uuid,uuid) FROM PUBLIC;
