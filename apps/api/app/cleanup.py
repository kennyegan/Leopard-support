"""Complete owned pilot retention; preserve the original demo study cleanup."""

import argparse
from .db import connection
from .config import settings
from psycopg.types.json import Jsonb


def cleanup(dry_run=True):
    if settings().app_mode == "pilot":
        return cleanup_pilot(dry_run)
    with connection() as conn:
        count = conn.execute(
            "SELECT count(*) AS n FROM messages WHERE created_at < now()-interval '30 days' AND text_redacted <> '[expired]'"
        ).fetchone()["n"]
        if not dry_run:
            conn.execute(
                "UPDATE messages SET text_redacted='[expired]',response=NULL WHERE created_at < now()-interval '30 days'"
            )
        return {"eligible_messages": count, "dry_run": dry_run}


def cleanup_pilot(dry_run=True):
    with connection() as conn:
        rows = conn.execute(
            "SELECT id,owner_id FROM sessions WHERE owner_id IS NOT NULL AND created_at < now()-(%s * interval '1 day')",
            (settings().retention_days,),
        ).fetchall()
        if not dry_run:
            for row in rows:
                conn.execute("SELECT purge_pilot_session(%s,%s)", (row["id"], row["owner_id"]))
            conn.execute("DELETE FROM pilot_logins WHERE expires_at < now()")
            conn.execute("DELETE FROM pilot_rate_windows WHERE expires_at < now()")
            conn.execute("DELETE FROM pilot_audit WHERE created_at < now()-interval '90 days'")
            conn.execute(
                "INSERT INTO pilot_audit(event,metadata) VALUES('retention_completed',%s)",
                (Jsonb({"deleted_sessions": len(rows)}),),
            )
        return {
            "eligible_sessions": len(rows),
            "dry_run": dry_run,
            "retention_days": settings().retention_days,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(cleanup(not args.apply))
