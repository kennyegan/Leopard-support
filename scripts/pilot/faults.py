"""Kill only this task's local pilot replicas while a synthetic turn is in flight."""

import concurrent.futures
import json
import time
from uuid import uuid4
from operations import ROOT, COMPOSE, client, command, post, sql


def ready(c):
    for _ in range(50):
        try:
            if c.get("/api/ready").status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.4)
    raise AssertionError("Pilot did not recover")


def main():
    c = client()
    fault = COMPOSE + ["-f", str(ROOT / "infra/fault.compose.yaml")]
    evidence = {"mode": "local-scripted", "checks": []}
    try:
        command(fault + ["up", "-d", "api", "api2"])
        ready(c)
        sid = post(c, "/api/sessions", {})["id"]
        request_id = str(uuid4())
        body = dict(text="qualification-pause I need to download Autodesk", request_id=request_id)
        before = int(sql("SELECT count(*) FROM pilot_audit WHERE event='qualification_attempt'"))
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(c.post, f"/api/sessions/{sid}/messages", json=body)
            for _ in range(60):
                if int(sql("SELECT count(*) FROM pilot_audit WHERE event='qualification_attempt'")) > before:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("Delayed interpretation was not reached")
            command(COMPOSE + ["kill", "-s", "SIGKILL", "api", "api2"])
            result = future.result(timeout=20)
            evidence["interrupted_http_status"] = result.status_code
            assert result.status_code in (502, 503, 504)
        assert sql(f"SELECT count(*) FROM messages WHERE session_id='{sid}'") == "0"
        assert sql(f"SELECT status FROM pilot_turns WHERE session_id='{sid}'") == "processing"
        command(COMPOSE + ["up", "-d", "api", "api2"])
        ready(c)
        retry = c.post(f"/api/sessions/{sid}/messages", json=body)
        assert retry.status_code == 409, retry.text
        evidence["checks"].append("process death leaves one durable in-flight claim and no partial messages")
        # Accelerate only this test record's lease clock; the process death is real.
        sql(f"UPDATE pilot_turns SET lease_expires_at=now()-interval '1 second' WHERE session_id='{sid}'")
        retry = c.post(f"/api/sessions/{sid}/messages", json=body)
        assert retry.status_code == 409 and "cannot be replayed automatically" in retry.text
        assert sql(f"SELECT status FROM pilot_turns WHERE session_id='{sid}'") == "uncertain"
        assert int(sql("SELECT count(*) FROM pilot_audit WHERE event='qualification_attempt'")) == before + 1
        evidence["checks"].append(
            "expired interrupted request becomes uncertain; same ID never starts a second attempt"
        )
        result = post(
            c, f"/api/sessions/{sid}/messages", dict(text="I want a person", request_id=str(uuid4()))
        )
        assert result["action"] == "HANDOFF" and result.get("ticket")
        evidence["checks"].append("restarted normal runtime accepts explicit handoff after uncertain turn")
        evidence.update(
            passed=True,
            session_id=sid,
            external_calls=0,
            lease_note="Only the synthetic record lease timestamp was accelerated after real SIGKILL",
        )
    finally:
        command(COMPOSE + ["up", "-d", "api", "api2"])
        (ROOT / "docs/pilot/results/process-death.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
