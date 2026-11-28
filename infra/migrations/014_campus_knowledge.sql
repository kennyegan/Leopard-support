-- Content versions remain immutable. Withdrawal is an independent access control.
ALTER TABLE corpora ADD COLUMN IF NOT EXISTS withdrawn_at timestamptz;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS withdrawn_at timestamptz;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS audiences jsonb NOT NULL DEFAULT '["campus"]';
ALTER TABLE articles ADD COLUMN IF NOT EXISTS content_owner text NOT NULL DEFAULT '';
ALTER TABLE articles ADD COLUMN IF NOT EXISTS reviewed_at date;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS review_due date;
ALTER TABLE sections ADD COLUMN IF NOT EXISTS content_kind text NOT NULL DEFAULT 'procedure'
 CHECK (content_kind IN ('procedure','information'));
-- Application administrator is not a content audience. Grant staff/student access explicitly.
ALTER TABLE pilot_invites ADD COLUMN IF NOT EXISTS knowledge_audiences jsonb NOT NULL DEFAULT '["campus"]';
