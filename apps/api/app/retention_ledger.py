"""Operator-only deletion ledger export/replay for backup restoration.

Keep this ledger in separate protected storage. A database backup alone cannot
remember user deletions that happened after the backup was taken.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
from .config import settings
from .db import connection


def export(path):
    with connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        watermark = conn.execute("SELECT now() AS at").fetchone()["at"]
        rows = conn.execute(
            "SELECT object_id,actor_id,created_at FROM pilot_audit WHERE event='conversation_deleted' AND created_at>now()-interval '90 days' ORDER BY created_at"
        ).fetchall()
        usage = conn.execute("SELECT * FROM provider_usage WHERE id=1").fetchone()
        invitations = conn.execute("SELECT email,role,active FROM pilot_invites ORDER BY email").fetchall()
    document = dict(
        version=2,
        exported_at=watermark.isoformat(),
        provider_usage={k: str(v) for k, v in usage.items()},
        invitations=invitations,
        deletions=[
            dict(
                session_id=str(r["object_id"]),
                owner_id=str(r["actor_id"]),
                deleted_at=r["created_at"].isoformat(),
            )
            for r in rows
        ],
    )
    target = Path(path)
    target.write_text(json.dumps(document, indent=2) + "\n")
    target.chmod(0o600)
    return {"exported_deletions": len(rows)}


def reconcile(path, backup_created_at):
    document = json.loads(Path(path).read_text())
    if document["version"] != 2 or datetime.fromisoformat(document["exported_at"]) <= datetime.fromisoformat(
        backup_created_at
    ):
        raise ValueError(
            "A current version-2 recovery ledger newer than the backup is required; keep restored service inaccessible"
        )
    deleted = 0
    with connection() as conn:
        usage = document["provider_usage"]
        # The recovery ledger is authoritative for grants; existing counters
        # may be newer and must never move backwards. Run with inference off.
        conn.execute(
            """UPDATE provider_usage SET calls=GREATEST(calls,%s),
            reserved_usd=GREATEST(reserved_usd,%s),reported_cost_usd=GREATEST(reported_cost_usd,%s),
            authorized_limit=%s,budget_usd=%s,budget_start_calls=%s WHERE id=1""",
            (
                usage["calls"],
                usage["reserved_usd"],
                usage["reported_cost_usd"],
                usage["authorized_limit"],
                usage["budget_usd"],
                usage["budget_start_calls"],
            ),
        )
        # Stale backups must not re-enable revoked invitations or old roles.
        conn.execute("UPDATE pilot_invites SET active=false")
        for invite in document["invitations"]:
            conn.execute(
                """INSERT INTO pilot_invites(email,role,active) VALUES(%s,%s,%s)
                ON CONFLICT(email) DO UPDATE SET role=EXCLUDED.role,active=EXCLUDED.active""",
                (invite["email"], invite["role"], invite["active"]),
            )
        for row in document["deletions"]:
            result = conn.execute(
                "SELECT purge_pilot_session(%s,%s) AS deleted", (row["session_id"], row["owner_id"])
            ).fetchone()
            deleted += int(result["deleted"])
        expired = conn.execute(
            "SELECT id,owner_id FROM sessions WHERE owner_id IS NOT NULL AND created_at<now()-(%s*interval '1 day')",
            (settings().retention_days,),
        ).fetchall()
        for row in expired:
            conn.execute("SELECT purge_pilot_session(%s,%s)", (row["id"], row["owner_id"]))
        # Restores must never restore previously revoked browser logins.
        conn.execute("DELETE FROM pilot_logins")
    return dict(
        replayed_deletions=deleted,
        expired_sessions=len(expired),
        logins_revoked=True,
        usage_reconciled=True,
        invitations_reconciled=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "reconcile"])
    parser.add_argument("path")
    parser.add_argument("--backup-created-at")
    args = parser.parse_args()
    if args.action == "reconcile" and not args.backup_created_at:
        parser.error("--backup-created-at is required")
    print(export(args.path) if args.action == "export" else reconcile(args.path, args.backup_created_at))


if __name__ == "__main__":
    main()
