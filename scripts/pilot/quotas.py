"""Prove shared limits across the two isolated API replicas without inference."""

import hashlib
import json
import time
from uuid import uuid4
from operations import ROOT, COMPOSE, command, client, sql

c = client()
assert c.get("/api/health").json()["provider"] == "scripted"
user = c.get("/api/auth/me").json()["user_id"]
key = hashlib.sha256(("request:" + user).encode()).hexdigest()
start = int(time.time()) // 60 * 60
sql(
    f"INSERT INTO pilot_rate_windows(key,window_start,count,expires_at) VALUES('{key}',{start},59,now()+interval '2 minutes') ON CONFLICT(key,window_start) DO UPDATE SET count=59;"
)
token = next(
    v["value"]
    for v in json.loads((ROOT / ".runtime/pilot/browser-state.json").read_text())["cookies"]
    if v["name"] == "__Host-techspot"
)
code = f"""import httpx,json
cookie={{'__Host-techspot':{token!r}}}
print(json.dumps([httpx.get('http://'+host+':8000/api/auth/me',cookies=cookie).status_code for host in ['api','api2']]))"""
try:
    codes = json.loads(command(COMPOSE + ["exec", "-T", "api", "python", "-"], input=code.encode()))
    assert codes == [200, 429], codes
finally:
    sql(f"DELETE FROM pilot_rate_windows WHERE key='{key}'")
seed = []
try:
    for _ in range(10):
        sid = str(uuid4())
        seed.append(sid)
        sql(
            f"INSERT INTO sessions(id,owner_id,mode,state) VALUES('{sid}','{user}','policy','{{}}'); INSERT INTO pilot_turns(id,session_id,request_id,input_hash,state_revision,status,requires_inference,lease_expires_at) VALUES('{uuid4()}','{sid}','{uuid4()}','synthetic-quota-fixture',0,'processing',true,now()+interval '1 minute');"
        )
    r = c.post("/api/sessions", json={})
    r.raise_for_status()
    target = r.json()["id"]
    denied = c.post(
        f"/api/sessions/{target}/messages",
        json=dict(text="I need to download Autodesk", request_id=str(uuid4())),
    )
    assert denied.status_code == 429 and "busy" in denied.text, denied.text
    handoff = c.post(
        f"/api/sessions/{target}/messages", json=dict(text="I want a person", request_id=str(uuid4()))
    )
    assert handoff.status_code == 200 and handoff.json()["action"] == "HANDOFF", handoff.text
finally:
    for sid in seed:
        sql(f"SELECT purge_pilot_session('{sid}','{user}')")
r = c.post("/api/sessions", content=b" " * 21000, headers={"Content-Type": "application/json"})
assert r.status_code == 413, r.text
result = dict(
    passed=True,
    replica_statuses=codes,
    inference_capacity_rejected=denied.status_code,
    handoff_at_capacity=handoff.status_code,
    ingress_body_limit=r.status_code,
    external_calls=0,
    fixture="Synthetic rate-window count and ten in-flight records seeded locally; fixtures purged after the test",
)
(ROOT / "docs/pilot/results/shared-quotas.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
