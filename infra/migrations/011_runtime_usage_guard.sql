-- Owners can perform isolated test/restore maintenance. The application role
-- cannot reset counters or change authorized allocations.
CREATE OR REPLACE FUNCTION monotonic_provider_usage() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF current_user='techspot_runtime' AND
    (NEW.calls < OLD.calls OR NEW.reserved_usd < OLD.reserved_usd
     OR NEW.reported_cost_usd < OLD.reported_cost_usd) THEN
  RAISE EXCEPTION 'Runtime cannot reset historical provider usage';
 END IF;
 RETURN NEW;
END; $$;
