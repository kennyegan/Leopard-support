"""Exercise the local admin monitor and zero-inference turn telemetry through HTTPS."""

import argparse
import json
import ssl
from uuid import uuid4

import httpx
from operations import ROOT, COMPOSE, command, sql

parser = argparse.ArgumentParser()
parser.add_argument("--live", action="store_true", help="Use one already-authorized synthetic provider call")
args = parser.parse_args()
before = json.loads(sql("SELECT row_to_json(p) FROM provider_usage p"))
identity = "monitor-" + uuid4().hex
email = identity + "@example.test"
sql(f"INSERT INTO pilot_invites(email,role) VALUES('{email}','admin')")
code = f"from app.auth import establish_login; from app.config import settings; print(establish_login(dict(iss=settings().oidc_issuer,sub={identity!r},email={email!r},email_verified=True)))"
token = command(COMPOSE + ["exec", "-T", "api", "python", "-c", code]).decode().strip()
try:
    with httpx.Client(
        base_url="https://localhost:3443",
        timeout=25,
        verify=ssl.create_default_context(cafile=ROOT / ".runtime/pilot/tls/cert.pem"),
        cookies={"__Host-techspot": token},
    ) as c:
        me = c.get("/api/auth/me")
        me.raise_for_status()
        if args.live:
            health = c.get("/api/health").json()
            assert health["provider"] == "openrouter" and health["ai_requests_remaining"] >= 1
        c.headers.update({"Origin": "https://localhost:3443", "X-CSRF-Token": me.json()["csrf_token"]})
        created = c.post("/api/sessions", json={})
        created.raise_for_status()
        sid = created.json()["id"]
        response = c.post(
            f"/api/sessions/{sid}/messages",
            json=dict(
                text="I need to download Autodesk" if args.live else "I want a person",
                request_id=str(uuid4()),
            ),
        )
        response.raise_for_status()
        assert response.json()["rule"] == ("graph_intake" if args.live else "explicit_human_request")
        monitor = c.get("/api/admin/operations")
        monitor.raise_for_status()
        data = monitor.json()
        assert {r["stage"] for r in data["stage_latency"]} == {
            "reservation",
            "preparation",
            "interpretation",
            "decision_before_commit",
        }
        assert isinstance(data["alerts"]["retention_overdue"], bool)
        assert token not in monitor.text and email not in monitor.text
        evidence = dict(
            passed=True,
            mode="real-provider" if args.live else "local-zero-inference",
            turn_id=response.json()["turn_id"],
            application_revision=response.json()["application_revision"],
            operations=data,
            checks=[
                "admin aggregate stages available through HTTPS",
                "retention overdue flag exposed",
                "monitor omits credentials and conversation text",
            ],
        )
        assert c.post("/api/auth/logout").status_code == 303
finally:
    sql(
        f"UPDATE pilot_invites SET active=false WHERE email='{email}'; DELETE FROM pilot_logins WHERE user_id IN (SELECT id FROM pilot_users WHERE email='{email}');"
    )
after = json.loads(sql("SELECT row_to_json(p) FROM provider_usage p"))
if args.live:
    assert after["calls"] == before["calls"] + 1
else:
    assert before == after
evidence.update(budget_before=before, budget_after=after, external_calls=int(args.live))
name = "monitoring-provider.json" if args.live else "monitoring-container.json"
(ROOT / "docs/pilot/results" / name).write_text(json.dumps(evidence, indent=2) + "\n")
print(json.dumps(dict(passed=True, external_calls=int(args.live), stage_count=len(data["stage_latency"]))))
