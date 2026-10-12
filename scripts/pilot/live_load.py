"""Ten simultaneous authenticated synthetic turns; never grants provider spend."""

import concurrent.futures
import json
import math
import ssl
import threading
import time
from uuid import uuid4

import httpx
from operations import ROOT, COMPOSE, command, sql

context = ssl.create_default_context(cafile=ROOT / ".runtime/pilot/tls/cert.pem")
health = httpx.get("https://localhost:3443/api/health", verify=context).json()
assert health["provider"] == "openrouter" and health["external_ai_enabled"]
before = json.loads(sql("SELECT row_to_json(p) FROM provider_usage p"))
assert health["ai_requests_remaining"] >= 10
clients = []
for _ in range(10):
    identity = "load-" + uuid4().hex
    email = identity + "@example.test"
    sql(f"INSERT INTO pilot_invites(email,role) VALUES('{email}','tester')")
    code = f"from app.auth import establish_login; from app.config import settings; print(establish_login(dict(iss=settings().oidc_issuer,sub={identity!r},email={email!r},email_verified=True)))"
    token = command(COMPOSE + ["exec", "-T", "api", "python", "-c", code]).decode().strip()
    c = httpx.Client(
        base_url="https://localhost:3443", verify=context, timeout=25, cookies={"__Host-techspot": token}
    )
    me = c.get("/api/auth/me")
    me.raise_for_status()
    c.headers.update({"Origin": "https://localhost:3443", "X-CSRF-Token": me.json()["csrf_token"]})
    created = c.post("/api/sessions", json={})
    created.raise_for_status()
    clients.append((c, created.json()["id"]))

barrier = threading.Barrier(10)


def run(item):
    c, sid = item
    barrier.wait()
    start = time.perf_counter()
    try:
        r = c.post(
            f"/api/sessions/{sid}/messages",
            json=dict(text="I need to download Autodesk", request_id=str(uuid4())),
        )
        return dict(
            session_id=sid,
            status=r.status_code,
            elapsed_ms=round((time.perf_counter() - start) * 1000),
            reply=r.json(),
        )
    finally:
        c.close()


with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
    results = list(pool.map(run, clients))
times = sorted(r["elapsed_ms"] for r in results)
passed = all(r["status"] == 200 and r["reply"].get("question_field") == "system_or_app" for r in results)
evidence = dict(
    mode="real-provider",
    health_manifest=health,
    simultaneous_sessions=10,
    identity="direct synthetic fixtures; OIDC qualified separately",
    results=results,
    budget_before=before,
    budget_after=json.loads(sql("SELECT row_to_json(p) FROM provider_usage p")),
    percentiles_ms={str(p): times[math.ceil(p / 100 * len(times)) - 1] for p in (50, 95, 99)},
    passed=passed,
    p95_under_8_seconds=times[-1] < 8000,
)
(ROOT / "docs/pilot/results/live-load.json").write_text(json.dumps(evidence, indent=2) + "\n")
print(json.dumps({k: evidence[k] for k in ("passed", "percentiles_ms", "p95_under_8_seconds")}))
raise SystemExit(0 if passed else 1)
