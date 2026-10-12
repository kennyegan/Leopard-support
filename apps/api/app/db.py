from contextlib import contextmanager
import hashlib
import psycopg
from psycopg_pool import ConnectionPool
from threading import Lock
from psycopg.rows import dict_row
from .config import ROOT, settings

_pools = {}
_pool_lock = Lock()


def pool():
    cfg = settings()
    key = (cfg.database_url, cfg.pool_size)
    with _pool_lock:
        if key not in _pools:
            _pools[key] = ConnectionPool(
                cfg.database_url,
                min_size=1,
                max_size=cfg.pool_size,
                max_waiting=cfg.pool_size,
                timeout=3,
                open=True,
                kwargs={
                    "row_factory": dict_row,
                    "connect_timeout": 3,
                    "options": "-c statement_timeout=15000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=20000",
                },
            )
        return _pools[key]


def close_pools():
    with _pool_lock:
        for item in _pools.values():
            item.close()
        _pools.clear()


@contextmanager
def connection():
    context = (
        pool().connection()
        if settings().app_mode == "pilot"
        else psycopg.connect(settings().database_url, row_factory=dict_row)
    )
    with context as conn:
        yield conn


def migrate():
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(741321)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations(name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for migration in sorted((ROOT / "infra/migrations").glob("*.sql")):
            digest = hashlib.sha256(migration.read_bytes()).hexdigest()
            applied = conn.execute(
                "SELECT sha256 FROM schema_migrations WHERE name=%s", (migration.name,)
            ).fetchone()
            if applied:
                if applied["sha256"] != digest:
                    raise ValueError(f"Applied migration checksum changed: {migration.name}")
                continue
            conn.execute(migration.read_text())
            conn.execute("INSERT INTO schema_migrations(name,sha256) VALUES(%s,%s)", (migration.name, digest))


if __name__ == "__main__":
    migrate()
