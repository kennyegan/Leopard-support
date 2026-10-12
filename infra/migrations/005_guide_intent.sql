ALTER TABLE sections ADD COLUMN IF NOT EXISTS request_types jsonb NOT NULL DEFAULT '["troubleshoot"]'::jsonb;
ALTER TABLE sections ADD COLUMN IF NOT EXISTS reference_links jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE sections ADD COLUMN IF NOT EXISTS workflow jsonb NOT NULL DEFAULT '[]'::jsonb;
