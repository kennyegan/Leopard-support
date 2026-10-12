-- Runtime role receives no access to this internal authorization table.
CREATE TABLE IF NOT EXISTS pilot_deletion_authorizations (
 session_id uuid PRIMARY KEY, transaction_id bigint NOT NULL
);
REVOKE ALL ON pilot_deletion_authorizations FROM PUBLIC;

CREATE OR REPLACE FUNCTION immutable_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' AND EXISTS (
  SELECT 1 FROM public.pilot_deletion_authorizations
  WHERE session_id=OLD.session_id AND transaction_id=txid_current()
 ) THEN RETURN OLD; END IF;
 RAISE EXCEPTION 'Decision snapshots are immutable';
END; $$;

CREATE OR REPLACE FUNCTION purge_pilot_session(target uuid, expected_owner uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 PERFORM 1 FROM public.sessions WHERE id=target AND owner_id=expected_owner FOR UPDATE;
 IF NOT FOUND OR expected_owner IS NULL THEN RETURN false; END IF;
 INSERT INTO public.pilot_deletion_authorizations VALUES(target,txid_current());
 DELETE FROM public.feedback WHERE session_id=target;
 DELETE FROM public.tickets WHERE session_id=target;
 DELETE FROM public.state_snapshots WHERE session_id=target;
 DELETE FROM public.messages WHERE session_id=target;
 DELETE FROM public.sessions WHERE id=target;
 DELETE FROM public.pilot_deletion_authorizations WHERE session_id=target;
 INSERT INTO public.pilot_audit(event,actor_id,object_id) VALUES('conversation_deleted',expected_owner,target);
 RETURN true;
END; $$;
REVOKE ALL ON FUNCTION purge_pilot_session(uuid,uuid) FROM PUBLIC;
