"""Explicit owner-only release job: migration, immutable corpus, runtime grants."""

import os
from psycopg import sql
from .db import connection, migrate
from .ingest import ingest
from .config import settings


def grant_runtime(password):
    if len(password) < 32:
        raise ValueError("A separate strong runtime database password is required")
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='techspot_runtime'").fetchone():
            conn.execute("CREATE ROLE techspot_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
        conn.execute(sql.SQL("ALTER ROLE techspot_runtime PASSWORD {}").format(sql.Literal(password)))
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute("GRANT USAGE ON SCHEMA public TO techspot_runtime")
        conn.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM techspot_runtime")
        conn.execute(
            "GRANT SELECT ON corpora,articles,sections,schema_migrations,pilot_invites,provider_usage TO techspot_runtime"
        )
        conn.execute(
            "GRANT SELECT,INSERT,UPDATE ON sessions,messages,tickets,pilot_users,pilot_logins,pilot_rate_windows,pilot_turns TO techspot_runtime"
        )
        conn.execute("GRANT SELECT,INSERT ON state_snapshots,feedback,pilot_audit TO techspot_runtime")
        conn.execute("GRANT DELETE ON pilot_logins TO techspot_runtime")
        conn.execute(
            "GRANT UPDATE(calls,reserved_usd,reported_cost_usd) ON provider_usage TO techspot_runtime"
        )
        conn.execute("GRANT EXECUTE ON FUNCTION purge_pilot_session(uuid,uuid) TO techspot_runtime")
        conn.execute("GRANT EXECUTE ON FUNCTION lock_pilot_invitation(text) TO techspot_runtime")
        conn.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO techspot_runtime")


def main():
    if settings().app_mode != "pilot":
        raise ValueError("Explicit pilot operator configuration is required")
    migrate()
    result = ingest()
    grant_runtime(os.environ.get("RUNTIME_DB_PASSWORD", ""))
    print({"release": "migrated_and_ingested", "corpus": result})


if __name__ == "__main__":
    main()
