"""Live HTTP trajectories. Requires make dev. Never invokes a provider directly."""

import json
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"


def run():
    traces = []
    with httpx.Client(base_url=BASE, timeout=30) as c:
        health = c.get("/health")
        health.raise_for_status()
        assert health.json()["embedding"] == "BAAI/bge-small-en-v1.5"
        assert health.json()["provider"] == "scripted" and not health.json()["external_ai_enabled"]

        def trajectory(name, inputs):
            s = c.post("/api/sessions", json={"mode": "policy"}).json()["id"]
            turns = []
            for text in inputs:
                start = time.perf_counter()
                r = c.post(f"/api/sessions/{s}/messages", json={"text": text})
                r.raise_for_status()
                turns.append(
                    {"input": text, "response": r.json(), "latency_seconds": time.perf_counter() - start}
                )
            history = c.get(f"/api/sessions/{s}").json()
            snapshots = c.get(f"/api/sessions/{s}/snapshots").json()
            result = {
                "name": name,
                "session_id": s,
                "turns": turns,
                "persisted": history,
                "snapshots": snapshots,
            }
            traces.append(result)
            return result

        d1 = trajectory(
            "D1 clear", ["My demo-campus Wi-Fi stopped working on macOS and reports a demo credential error."]
        )
        a = d1["turns"][-1]["response"]
        assert a["action"] == "ANSWER", a
        assert a["sources"][0]["id"] in ["wifi-mac", "wifi-mac-alternate"]
        source = c.get("/api/guides/" + a["sources"][0]["id"]).json()[0]
        assert source["is_synthetic"] and a["steps"] == source["steps"]
        r = c.post(
            "/api/feedback",
            json=dict(
                session_id=d1["session_id"],
                message_id=a["id"],
                snapshot_id=a["snapshot_id"],
                kind="fix",
                value="yes",
            ),
        )
        r.raise_for_status()
        d2 = trajectory(
            "D2 clarify", ["Wi-Fi isn't working.", "macOS on demo-campus with a demo credential error"]
        )
        assert [x["response"]["action"] for x in d2["turns"]] == ["ASK", "ANSWER"]
        assert d2["snapshots"][0]["state_json"]["details"]["os"] is None
        assert d2["snapshots"][1]["state_json"]["details"]["os"] == "macOS"
        assert len(d2["snapshots"][1]["state_json"]["questions"]) == 1
        d3 = trajectory("D3 unsupported", ["Can you repair my computer remotely or access my account?"])
        assert d3["turns"][0]["response"]["action"] == "HANDOFF"
        d4 = trajectory(
            "D4 repeated failure",
            [
                "My demo-campus Wi-Fi stopped working on macOS and reports a demo credential error.",
                "No, that did not fix it.",
                "No, that did not fix it.",
            ],
        )
        assert [x["response"]["action"] for x in d4["turns"]] == ["ANSWER", "ANSWER", "HANDOFF"]
        assert d4["turns"][-1]["response"]["rule"] == "repeated_failure"
        assert len(d4["turns"][-1]["response"]["state"]["attempted_guides"]) == 2
        d5 = trajectory("D5 human", ["I want to talk to TechSpot staff."])
        assert d5["turns"][0]["response"]["rule"] == "explicit_human_request"
        edit = c.put(
            f"/api/sessions/{d5['session_id']}/ticket",
            json={"draft": "Demo draft edit. Contact me at jane@example.com password=hidden123"},
        )
        edit.raise_for_status()
        assert edit.json()["edited"] and "jane@example.com" not in edit.text and "hidden123" not in edit.text
        d5["edited_ticket"] = edit.json()
        assert c.get(f"/api/sessions/{d5['session_id']}").json()["ticket"]["draft"] == edit.json()["draft"]
    out = ROOT / "docs/mvp/results"
    out.mkdir(exist_ok=True, parents=True)
    (out / "trajectories.json").write_text(
        json.dumps({"health": health.json(), "trajectories": traces}, indent=2)
    )
    lines = [
        "# Live HTTP demonstration transcripts",
        "",
        "Provider: scripted offline; actual FastEmbed/pgvector retrieval. No external LLM.",
        "",
    ]
    for t in traces:
        lines += [f"## {t['name']}", f"Session: `{t['session_id']}`", ""]
        for row in t["turns"]:
            a = row["response"]
            lines += [
                f"User: {row['input']}",
                f"Assistant: **{a['action']}** (`{a['rule']}`) — {a['text']}",
                f"Sources: {', '.join(s['id'] for s in a['sources']) or 'none'}; questions: {len(a['state']['questions'])}; failures: {a['state']['failures']}",
                "",
            ]
    (ROOT / "docs/mvp/DEMO_TRANSCRIPTS.md").write_text("\n".join(lines))
    print(
        "PASS D1–D5 through live HTTP; snapshots, source steps, feedback and redacted editable tickets verified."
    )


if __name__ == "__main__":
    run()
