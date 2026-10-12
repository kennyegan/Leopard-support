"""Local-only container drills. Creates isolated synthetic sessions and a restore DB."""

import concurrent.futures
import hashlib
import json
from pathlib import Path
import ssl
import statistics
import subprocess
import time
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(ROOT / ".runtime/pilot/compose.env"),
    "-f",
    str(ROOT / "infra/pilot.compose.yaml"),
    "-f",
    str(ROOT / "infra/qualification.compose.yaml"),
]
RESULT = ROOT / "docs/pilot/results/operations.json"


def command(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs).stdout


def sql(statement, database="techspot_pilot"):
    return (
        command(
            COMPOSE
            + [
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "techspot_owner",
                "-d",
                database,
                "-v",
                "ON_ERROR_STOP=1",
                "-At",
            ],
            input=statement.encode(),
        )
        .decode()
        .strip()
    )


def client():
    state = json.loads((ROOT / ".runtime/pilot/browser-state.json").read_text())
    c = httpx.Client(
        base_url="https://localhost:3443",
        verify=ssl.create_default_context(cafile=ROOT / ".runtime/pilot/tls/cert.pem"),
        timeout=25,
    )
    for cookie in state["cookies"]:
        if cookie["name"] == "__Host-techspot":
            c.cookies.set(cookie["name"], cookie["value"])
    me = c.get("/api/auth/me")
    me.raise_for_status()
    c.headers.update({"Origin": "https://localhost:3443", "X-CSRF-Token": me.json()["csrf_token"]})
    return c


def post(c, path, data):
    r = c.post(path, json=data)
    r.raise_for_status()
    return r.json()


def main():
    c = client()
    evidence = {"mode": "local-scripted", "checks": []}
    identity = c.get("/api/auth/me").json()["user_id"]
    # Reset only this synthetic test user's local quota windows so the drill is
    # reproducible. This never touches provider allocation/usage counters.
    keys = [hashlib.sha256((prefix + identity).encode()).hexdigest() for prefix in ("request:", "turn-user:")]
    sql("DELETE FROM pilot_rate_windows WHERE key IN ('" + "','".join(keys) + "');")
    evidence["quota_fixture"] = (
        "Only the synthetic drill user's local rate windows were reset before the test"
    )
    # Runtime grants are exercised in the actual container, not as a DB owner.
    check_code = """from app.db import connection
import psycopg
checks=[]
for statement in ["UPDATE pilot_invites SET active=false", "UPDATE provider_usage SET authorized_limit=99999", "UPDATE provider_usage SET calls=calls-1", "INSERT INTO pilot_deletion_authorizations VALUES(gen_random_uuid(),txid_current())", "DELETE FROM state_snapshots", "CREATE TABLE unauthorized_probe(id int)"]:
 try:
  with connection() as conn: conn.execute(statement)
 except (psycopg.errors.InsufficientPrivilege,psycopg.errors.RaiseException): checks.append(True)
 else: raise AssertionError('Unexpected runtime privilege')
print(len(checks))"""
    assert command(COMPOSE + ["exec", "-T", "api", "python", "-c", check_code]).decode().strip() == "6"
    evidence["checks"].append(
        "runtime cannot alter invitations, increase allocation, reset usage, bypass deletion markers, delete snapshots or create tables"
    )
    sessions = [post(c, "/api/sessions", {})["id"] for _ in range(10)]

    def one(sid):
        started = time.perf_counter()
        response = post(
            c,
            f"/api/sessions/{sid}/messages",
            dict(text="Install AutoCAD on Windows with Autodesk education access", request_id=str(uuid4())),
        )
        return dict(
            session_id=sid,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            action=response["action"],
            node=response["state"]["active_node"],
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(one, sessions))
    assert all(r["action"] == "ANSWER" and r["node"] == "check-1" for r in results)
    times = sorted(r["elapsed_ms"] for r in results)
    evidence["load"] = dict(
        concurrent_sessions=10,
        results=results,
        p50_ms=statistics.median(times),
        p95_ms=times[-1],
        note="Ten-sample nearest-rank p95; offline model only, not the real-provider SLA",
    )
    evidence["checks"].append("ten simultaneous sessions commit consistently through two API replicas")
    RESULT.write_text(json.dumps(evidence, indent=2) + "\n")
    # A fully populated synthetic conversation demonstrates backup fidelity and re-expiration.
    sid = post(c, "/api/sessions", {})["id"]
    first = post(
        c, f"/api/sessions/{sid}/messages", dict(text="I need to download Autodesk", request_id=str(uuid4()))
    )
    post(
        c,
        "/api/feedback",
        dict(
            session_id=sid,
            message_id=first["id"],
            snapshot_id=first["snapshot_id"],
            kind="question",
            value="yes",
        ),
    )
    post(c, f"/api/sessions/{sid}/messages", dict(text="I want a person", request_id=str(uuid4())))
    r = c.put(f"/api/sessions/{sid}/ticket", json={"draft": "Synthetic restore drill draft"})
    r.raise_for_status()
    sql(f"UPDATE sessions SET created_at=now()-interval '40 days' WHERE id='{sid}';")
    tables = ["sessions", "messages", "state_snapshots", "tickets", "feedback", "pilot_turns"]

    def counts(database):
        return {table: int(sql(f"SELECT count(*) FROM {table}", database)) for table in tables}

    before = counts("techspot_pilot")
    backup = command(
        COMPOSE + ["exec", "-T", "db", "pg_dump", "-U", "techspot_owner", "-d", "techspot_pilot", "-Fc"]
    )
    (ROOT / ".runtime/pilot/qualification-backup.dump").write_bytes(backup)
    restored = "qualification_restore_" + uuid4().hex[:10]
    sql(f"CREATE DATABASE {restored};")
    command(
        COMPOSE
        + ["exec", "-T", "db", "pg_restore", "-U", "techspot_owner", "-d", restored, "--exit-on-error"],
        input=backup,
    )
    assert counts(restored) == before
    evidence["restore"] = dict(
        database=restored, sha256=hashlib.sha256(backup).hexdigest(), bytes=len(backup), table_counts=before
    )
    sql(
        "SELECT purge_pilot_session(id,owner_id) FROM sessions WHERE owner_id IS NOT NULL AND created_at<now()-interval '30 days';",
        restored,
    )
    for table in tables:
        column = "id" if table == "sessions" else "session_id"
        assert sql(f"SELECT count(*) FROM {table} WHERE {column}='{sid}';", restored) == "0"
    evidence["checks"].append(
        "pg_dump/pg_restore retains all table counts; re-expiration removes restored raw and derived conversation data"
    )
    assert c.get("/api/health").json()["external_ai_enabled"] is False
    evidence["external_calls"] = 0
    evidence["passed"] = True
    RESULT.write_text(json.dumps(evidence, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": True,
                "checks": len(evidence["checks"]),
                "load_p95_ms": times[-1],
                "restored_database": restored,
            }
        )
    )


if __name__ == "__main__":
    main()
