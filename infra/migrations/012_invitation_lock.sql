-- Allow the login transaction to lock an active invitation without giving the
-- runtime role permission to change the invitation allowlist.
CREATE OR REPLACE FUNCTION lock_pilot_invitation(target text)
RETURNS TABLE(email text,role text) LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT i.email,i.role FROM public.pilot_invites i WHERE i.email=target AND i.active FOR SHARE;
$$;
REVOKE ALL ON FUNCTION lock_pilot_invitation(text) FROM PUBLIC;
