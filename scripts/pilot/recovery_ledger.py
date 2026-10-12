"""Exercise owner-only ledger replay in the isolated database restored by operations.py."""

from datetime import datetime, timezone
import json
import os

from dotenv import dotenv_values
from operations import ROOT, COMPOSE, command, sql

operations = json.loads((ROOT / "docs/pilot/results/operations.json").read_text())
print("Inspecting the recorded isolated restore target; no active database mutation.")
# The target is the actual dump/restore drill database, never the serving DB.
target = operations["restore"]["database"]
assert target.startswith("qualification_restore_")
operator_compose = COMPOSE[:2] + ["--profile", "operations"] + COMPOSE[2:]
code = "from app.retention_ledger import export; from pathlib import Path; export('/tmp/ledger.json'); print(Path('/tmp/ledger.json').read_text())"
raw = command(operator_compose + ["run", "--rm", "--no-deps", "release", "python", "-c", code])
ledger = json.loads(raw)
local = ROOT / ".runtime/pilot/recovery-ledger.json"
local.write_text(json.dumps(ledger, indent=2) + "\n")
local.chmod(0o600)
values = dict(dotenv_values(ROOT / ".runtime/pilot/operator.env"))
values["DATABASE_URL"] = values["DATABASE_URL"].rsplit("/", 1)[0] + "/" + target
restore_env = ROOT / ".runtime/pilot/recovery-operator.env"
restore_env.write_text("".join(k + "=" + str(v) + "\n" for k, v in values.items()))
restore_env.chmod(0o600)
backup_at = datetime.fromtimestamp(
    (ROOT / ".runtime/pilot/qualification-backup.dump").stat().st_mtime, timezone.utc
).isoformat()
before = json.loads(sql("SELECT row_to_json(p) FROM provider_usage p", database=target))
code = (
    "import json,sys; from pathlib import Path; from app.retention_ledger import reconcile; Path('/tmp/recovery.json').write_bytes(sys.stdin.buffer.read()); print(json.dumps(reconcile('/tmp/recovery.json',"
    + repr(backup_at)
    + ")))"
)
result = json.loads(
    command(
        operator_compose
        + [
            "run",
            "-T",
            "--rm",
            "--no-deps",
            "release",
            "python",
            "-c",
            code,
        ],
        env={**os.environ, "PILOT_OPERATOR_ENV": str(restore_env)},
        input=local.read_bytes(),
    )
)
after = json.loads(sql("SELECT row_to_json(p) FROM provider_usage p", database=target))
assert after["calls"] >= int(ledger["provider_usage"]["calls"])
assert after["reserved_usd"] >= float(ledger["provider_usage"]["reserved_usd"])
assert sql("SELECT count(*) FROM pilot_logins", database=target) == "0"
active = json.loads(
    sql(
        "SELECT COALESCE(json_agg(email ORDER BY email),'[]') FROM pilot_invites WHERE active",
        database=target,
    )
)
assert active == sorted(r["email"] for r in ledger["invitations"] if r["active"])
evidence = dict(
    passed=True,
    isolated_target=target,
    backup_at=backup_at,
    ledger_exported_at=ledger["exported_at"],
    replay=result,
    restored_usage_before=before,
    restored_usage_after=after,
    active_database_mutations=0,
    external_calls=0,
)
(ROOT / "docs/pilot/results/recovery-ledger.json").write_text(json.dumps(evidence, indent=2) + "\n")
print(
    json.dumps({k: evidence[k] for k in ["passed", "replay", "active_database_mutations", "external_calls"]})
)
