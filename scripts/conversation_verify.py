"""Bounded synthetic HTTP trajectories. Live use requires an authorized spend grant."""

import argparse
import json
import subprocess
from pathlib import Path
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "failures": [
        "My home Wi-Fi disconnects every few minutes on my laptop",
        "I tried those checks and it still disconnects",
        "I tried that too. No, that did not fix it.",
    ],
    "correction": [
        "My home Wi-Fi disconnects on my macOS laptop",
        "Actually this laptop runs Windows, not macOS. The same home Wi-Fi still disconnects; I haven't tried the checks yet.",
    ],
    "unknown": ["wifi", "I don't know how to describe it. I'm not sure."],
    "unfamiliar": [
        "The room reservation widget in Orbit Scheduler keeps changing my selected room",
        "It is on my laptop, and there is no error message",
    ],
    "printing": [
        "My printer queue on Windows is stuck and nothing comes out",
        "New issue: my email inbox isn't receiving new messages on the same Windows laptop",
    ],
    "human": ["I want a person to help with my connection problem"],
    "unsupported": ["Can you repair my computer remotely or access my account?"],
}


def check_case(name, turns):
    first, last = turns[0], turns[-1]
    if name == "failures":
        assert [r["action"] for r in turns] == ["ANSWER", "ANSWER", "HANDOFF"]
        assert first["sources"][0]["id"] != turns[1]["sources"][0]["id"]
        assert last["rule"] == "repeated_failure" and last["state"]["failures"] == 2
    elif name == "correction":
        assert last["state"]["details"]["os"] == "Windows"
        assert last["state"]["details"]["network"] == first["state"]["details"]["network"]
        assert last["state"]["failures"] == 0
        assert first["state"]["problem_id"] == last["state"]["problem_id"]
    elif name == "unknown":
        assert first["action"] == "ASK" and first["question_field"] == "symptom"
        assert last["question_field"] != first["question_field"]
    elif name == "unfamiliar":
        assert first["rule"] != "unsupported_scope"
        assert "demo-" not in json.dumps(last["state"]["details"]).lower()
    elif name == "printing":
        assert first["state"]["category"] == "printing" and last["state"]["category"] == "email"
        assert first["state"]["problem_id"] != last["state"]["problem_id"]
    elif name == "unsupported":
        assert last["rule"] == "unsupported_scope" and "ticket" in last
        assert not last["steps"]
    else:
        assert last["rule"] == "explicit_human_request" and "ticket" in last


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["scripted", "openrouter"], default="scripted")
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--output", default="docs/conversational/results/api.json")
    args = parser.parse_args()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "cases": [],
        "passed": False,
    }
    try:
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=25) as c:
            health = c.get("/api/health").json()
            report["health"] = health
            assert health["provider"] == args.provider and health["dialogue_mode"] == "conversational"
            for name in args.cases.split(","):
                sid = c.post("/api/sessions", json={"mode": "policy"}).json()["id"]
                case = {"name": name, "session_id": sid, "turns": [], "passed": False}
                report["cases"].append(case)
                for text in CASES[name]:
                    request_id = str(uuid4())
                    r = c.post(f"/api/sessions/{sid}/messages", json={"text": text, "request_id": request_id})
                    r.raise_for_status()
                    answer = r.json()
                    case["turns"].append({"input": text, "response": answer})
                    assert answer["response_kind"] != "service_error", answer["text"]
                    assert len(answer["state"]["questions"]) <= 3
                    for source in answer["sources"]:
                        guide = c.get(f"/api/guides/{source['id']}").json()
                        assert all(
                            step in [s for section in guide for s in section["steps"]]
                            for step in answer["steps"]
                        )
                check_case(name, [t["response"] for t in case["turns"]])
                history = c.get(f"/api/sessions/{sid}").json()
                assert len(history["messages"]) == 2 * len(case["turns"])
                assert len(c.get(f"/api/sessions/{sid}/snapshots").json()) == len(case["turns"])
                if case["turns"][-1]["response"].get("ticket"):
                    saved = c.put(
                        f"/api/sessions/{sid}/ticket",
                        json={
                            "draft": "Synthetic review: connection remains unavailable. Nothing submitted."
                        },
                    ).json()
                    assert c.get(f"/api/sessions/{sid}").json()["ticket"]["draft"] == saved["draft"]
                case["passed"] = True
                print(
                    f"PASS {name}: " + " → ".join(t["response"]["response_kind"] for t in case["turns"]),
                    flush=True,
                )
            report["passed"] = True
    finally:
        output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
