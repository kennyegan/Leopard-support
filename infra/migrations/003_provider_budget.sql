-- Preserve historical usage; budgets can only grow through explicit owner approval.
ALTER TABLE provider_usage ADD COLUMN IF NOT EXISTS authorized_limit integer NOT NULL DEFAULT 15;
ALTER TABLE provider_usage ADD COLUMN IF NOT EXISTS budget_start_calls integer NOT NULL DEFAULT 0;
ALTER TABLE provider_usage ADD COLUMN IF NOT EXISTS budget_usd numeric(12,6) NOT NULL DEFAULT 0;
ALTER TABLE provider_usage ADD COLUMN IF NOT EXISTS reserved_usd numeric(12,6) NOT NULL DEFAULT 0;
ALTER TABLE provider_usage ADD COLUMN IF NOT EXISTS reported_cost_usd numeric(12,6) NOT NULL DEFAULT 0;
