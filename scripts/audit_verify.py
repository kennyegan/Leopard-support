"""Replay the preserved audit inputs against the real, synthetic-only local API."""

import json
from pathlib import Path
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[1]
original = json.loads((ROOT / "evals/regression-inputs.json").read_text())
report = {"cases": {}}
with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30) as client:

    def get(path):
        response = client.get(path)
        response.raise_for_status()
        return response.json()

    def post(path, body):
        response = client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    report["health"] = get("/health")
    assert report["health"]["provider"] == "scripted"
    assert report["health"]["external_ai_enabled"] is False
    for name, case in original["cases"].items():
        sid = post("/api/sessions", {"mode": "policy"})["id"]
        turns = []
        for turn in case["turns"]:
            result = post(
                f"/api/sessions/{sid}/messages", {"text": turn["input"], "request_id": str(uuid4())}
            )
            turns.append({"input": turn["input"], "response": result})
        report["cases"][name] = {
            "session_id": sid,
            "turns": turns,
            "snapshots": get(f"/api/sessions/{sid}/snapshots"),
        }
        print(name, [(t["response"]["action"], t["response"]["state"]["failures"]) for t in turns])

    cases = report["cases"]
    chain = [t["response"] for t in cases["changed_error_failure"]["turns"]]
    assert [r["state"]["failures"] for r in chain] == [0, 1, 2]
    assert chain[-1]["rule"] == "repeated_failure"
    assert chain[0]["sources"][0]["id"] != chain[1]["sources"][0]["id"]
    for name in ("macbook_assumption", "bios_alias"):
        result = cases[name]["turns"][0]["response"]
        assert result["state"]["details"]["os"] is None and result["question_field"] == "os"
    followup = cases["followup_category"]["turns"][-1]["response"]
    assert followup["state"]["category"] == "email"
    assert followup["state"]["details"]["system_or_app"] == "Demo-Mail"
    assert followup["state"]["failures"] == 1
    assert cases["negated_human"]["turns"][0]["response"]["action"] == "ANSWER"
    assert cases["human"]["turns"][0]["response"]["rule"] == "explicit_human_request"
    assert cases["cap"]["turns"][-1]["response"]["rule"] == "question_cap"

    sid = cases["clear"]["session_id"]
    answer = cases["clear"]["turns"][0]["response"]
    vote = dict(
        session_id=sid, message_id=answer["id"], snapshot_id=answer["snapshot_id"], kind="fix", value="yes"
    )
    post("/api/feedback", vote)
    assert get(f"/api/sessions/{sid}")["state"]["outcome"] == "resolved"
    report["resolved_then_failed"] = post(
        f"/api/sessions/{sid}/messages", {"text": "Actually, that didn't work."}
    )
    assert report["resolved_then_failed"]["state"]["outcome"] == "open"
    assert report["resolved_then_failed"]["state"]["failures"] == 1
    vote["kind"] = "rating"
    first = post("/api/feedback", vote)
    second = post("/api/feedback", {**vote, "value": "no"})
    report["feedback_duplicate"] = dict(
        first=first, second=second, history=get(f"/api/sessions/{sid}")["feedback"]
    )
    assert second["duplicate"] and second["value"] == "yes"

    sid = post("/api/sessions", {"mode": "policy"})["id"]
    payload = dict(text="Wi-Fi isn't working.", request_id=str(uuid4()))
    first = post(f"/api/sessions/{sid}/messages", payload)
    second = post(f"/api/sessions/{sid}/messages", payload)
    history = get(f"/api/sessions/{sid}")
    snapshots = get(f"/api/sessions/{sid}/snapshots")
    assert first == second and len(history["messages"]) == 2
    assert len(history["state"]["questions"]) == 1 and len(snapshots) == 1
    report["idempotent_retry"] = dict(first=first, second=second, history=history, snapshots=snapshots)

report["status"] = "passed"
(ROOT / "docs/mvp/results/audit-regressions.json").write_text(json.dumps(report, indent=2) + "\n")
print("Audit API regressions passed. Browser races are independently covered in tests/audit.spec.ts.")
