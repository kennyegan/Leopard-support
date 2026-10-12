CREATE OR REPLACE FUNCTION monotonic_provider_usage() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.calls < OLD.calls OR NEW.reserved_usd < OLD.reserved_usd
    OR NEW.reported_cost_usd < OLD.reported_cost_usd THEN
  RAISE EXCEPTION 'Historical provider usage cannot be reset';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER provider_usage_monotonic BEFORE UPDATE ON provider_usage
FOR EACH ROW EXECUTE FUNCTION monotonic_provider_usage();
