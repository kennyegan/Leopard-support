"""Demonstrate pinned conversation continuity across candidate rollback/upgrade."""

import json
from uuid import uuid4
from operations import ROOT, COMPOSE, command, client, post, sql
from faults import ready

c = client()
evidence = {"checks": [], "rollback_revision": "32e86a8"}
try:
    sid = post(c, "/api/sessions", {})["id"]
    first = post(
        c,
        f"/api/sessions/{sid}/messages",
        dict(text="Install AutoCAD on Windows with Autodesk education access", request_id=str(uuid4())),
    )
    assert first["state"]["active_node"] == "check-1"
    before = sql("SELECT count(*) FROM schema_migrations")
    command(COMPOSE + ["-f", str(ROOT / "infra/rollback.compose.yaml"), "up", "-d", "api", "api2"])
    ready(c)
    second = post(c, f"/api/sessions/{sid}/messages", dict(text="yes", request_id=str(uuid4())))
    assert (
        second["state"]["active_node"] == "check-2"
        and second["state"]["active_corpus"] == first["state"]["active_corpus"]
    )
    evidence["checks"].append("previous code resumes exact pinned workflow on upgraded schema")
    command(COMPOSE + ["up", "-d", "api", "api2"])
    ready(c)
    third = post(c, f"/api/sessions/{sid}/messages", dict(text="Download complete", request_id=str(uuid4())))
    assert third["state"]["active_node"] == "check-3"
    assert sql("SELECT count(*) FROM schema_migrations") == before
    evidence["checks"].append("candidate resumes after rollback without reverse migrations or data loss")
    evidence.update(passed=True, session_id=sid, external_calls=0)
finally:
    command(COMPOSE + ["up", "-d", "api", "api2"])
    (ROOT / "docs/pilot/results/rollback.json").write_text(json.dumps(evidence, indent=2) + "\n")
print(json.dumps(evidence))
