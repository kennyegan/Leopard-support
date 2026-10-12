"""Frozen conversation runner through HTTPS. Identity fixtures are synthetic.

This runner seeds test logins directly in the local qualification database; the
separate browser gate exercises OIDC. It never grants provider spend.
"""

import argparse
import hashlib
import json
import ssl
import time
from uuid import uuid4
import httpx
from operations import ROOT, COMPOSE, command, sql


parser = argparse.ArgumentParser()
parser.add_argument("--split", choices=["development", "holdout", "all"], default="development")
parser.add_argument("--live", action="store_true")
parser.add_argument("--output", default="conversations-offline-development.json")
parser.add_argument("--case-ids", help="Comma-separated frozen case IDs for repeat trials")
parser.add_argument("--trial", type=int, default=1)
parser.add_argument("--suite", choices=["v1", "v2"], default="v1")
args = parser.parse_args()
path = ROOT / "evals/pilot" / ("cases.json" if args.suite == "v1" else "requalification-v2.json")
checksum = path.parent / "FROZEN.sha256" if args.suite == "v1" else path.with_suffix(".sha256")
assert hashlib.sha256(path.read_bytes()).hexdigest() == checksum.read_text().split()[0]
ssl_context = ssl.create_default_context(cafile=ROOT / ".runtime/pilot/tls/cert.pem")
health = httpx.get("https://localhost:3443/api/health", verify=ssl_context).json()
if args.live:
    if health["provider"] != "openrouter" or not health["external_ai_enabled"]:
        raise SystemExit("Live qualification requires an explicitly authorized running provider.")
else:
    if health["provider"] != "scripted" or health["external_ai_enabled"]:
        raise SystemExit("Offline runner refuses a paid provider.")
cases = [c for c in json.loads(path.read_text())["cases"] if args.split == "all" or c["split"] == args.split]
if args.case_ids:
    selected = set(args.case_ids.split(","))
    cases = [c for c in cases if c["id"] in selected]
    assert {c["id"] for c in cases} == selected
if args.live and health["ai_requests_remaining"] < sum(len(c["user_turns"]) for c in cases):
    raise SystemExit("Insufficient authorized attempts for this complete suite; allocation unchanged.")
evidence = dict(
    provider=health["provider"],
    mode="real-provider" if args.live else "scripted-diagnostic-only",
    corpus=health["corpus_version"],
    health_manifest=health,
    trial=args.trial,
    budget_before=json.loads(sql("SELECT row_to_json(p) FROM provider_usage p")),
    suite_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    independent_review="pending",
    identity="direct synthetic database fixture; browser OIDC qualified separately",
    cases=[],
)
out = ROOT / "docs/pilot/results" / args.output
if out.exists():
    raise SystemExit("Evidence output already exists; choose a new --output name to preserve the prior run.")
for case in cases:
    identifier = "eval-" + uuid4().hex
    email = identifier + "@example.test"
    sql(f"INSERT INTO pilot_invites(email,role) VALUES('{email}','tester');")
    code = f"from app.auth import establish_login; from app.config import settings; print(establish_login(dict(iss=settings().oidc_issuer,sub={identifier!r},email={email!r},email_verified=True)))"
    # Capture credentials in memory only. Never print or place in result artifacts.
    token = command(COMPOSE + ["exec", "-T", "api", "python", "-c", code]).decode().strip()
    with httpx.Client(
        base_url="https://localhost:3443", verify=ssl_context, timeout=25, cookies={"__Host-techspot": token}
    ) as c:
        me = c.get("/api/auth/me")
        me.raise_for_status()
        c.headers.update({"Origin": "https://localhost:3443", "X-CSRF-Token": me.json()["csrf_token"]})
        create = c.post("/api/sessions", json={})
        create.raise_for_status()
        sid = create.json()["id"]
        run = dict(id=case["id"], split=case["split"], session_id=sid, turns=[], invariant_failures=[])
        asked = set()
        for text in case["user_turns"]:
            start = time.perf_counter()
            r = c.post(f"/api/sessions/{sid}/messages", json=dict(text=text, request_id=str(uuid4())))
            elapsed = round((time.perf_counter() - start) * 1000)
            if r.status_code != 200:
                run["invariant_failures"].append(f"HTTP {r.status_code}")
                run["turns"].append(dict(user=text, status=r.status_code, elapsed_ms=elapsed))
                evidence["cases"].append(run)
                evidence["aborted"] = True
                evidence["budget_after"] = json.loads(sql("SELECT row_to_json(p) FROM provider_usage p"))
                out.write_text(json.dumps(evidence, indent=2) + "\n")
                raise SystemExit(f"HTTP {r.status_code}: inspect saved evidence before another attempt.")
            reply = r.json()
            run["turns"].append(dict(user=text, reply=reply, elapsed_ms=elapsed))
            if reply["response_kind"] == "service_error":
                run["invariant_failures"].append(
                    "provider unavailable; qualification stopped to preserve allowance"
                )
                evidence["cases"].append(run)
                evidence["aborted"] = True
                evidence["budget_after"] = json.loads(sql("SELECT row_to_json(p) FROM provider_usage p"))
                out.write_text(json.dumps(evidence, indent=2) + "\n")
                raise SystemExit("Provider failure: inspect saved evidence before another paid attempt.")
            if reply["action"] == "ASK" and reply["rule"] != "clarify_question":
                field = reply["question_field"]
                if field in asked:
                    run["invariant_failures"].append("repeated intake field " + str(field))
                asked.add(field)
            if len(reply["state"]["questions"]) > 3:
                run["invariant_failures"].append("intake bound exceeded")
            allowed = []
            for source in reply["sources"]:
                response = c.get(
                    "/api/guides/" + source["id"],
                    params={"version": source["corpus_version"], "section": source["section_id"]},
                )
                if response.status_code != 200:
                    run["invariant_failures"].append("source unavailable")
                else:
                    for section in response.json():
                        allowed.extend(section["steps"])
            if any(step not in allowed for step in reply["steps"]):
                run["invariant_failures"].append("step missing from cited source")
            if (
                reply["action"] == "HANDOFF"
                and reply["response_kind"] != "service_error"
                and not reply.get("ticket")
            ):
                run["invariant_failures"].append("handoff missing draft")
        last = run["turns"][-1].get("reply", {})
        run["end_state"] = last.get("state", {}).get("outcome", "http_error")
        run["expected_end"] = case["expected_end"]
        run["end_match"] = run["end_state"] == case["expected_end"]
        run["review_rubric"] = case["review"]
        evidence["cases"].append(run)
        out.write_text(json.dumps(evidence, indent=2) + "\n")
        print(
            json.dumps(
                dict(id=case["id"], end_match=run["end_match"], invariants=len(run["invariant_failures"]))
            ),
            flush=True,
        )
evidence["summary"] = dict(
    cases=len(evidence["cases"]),
    end_matches=sum(c["end_match"] for c in evidence["cases"]),
    invariant_failures=sum(len(c["invariant_failures"]) for c in evidence["cases"]),
    usefulness_qualified=False,
)
evidence["budget_after"] = json.loads(sql("SELECT row_to_json(p) FROM provider_usage p"))
out.write_text(json.dumps(evidence, indent=2) + "\n")
print(json.dumps(evidence["summary"]))
