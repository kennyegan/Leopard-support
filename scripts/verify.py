"""Capture exact verification commands, exits and logs; requires a running app for live checks."""

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=["checks", "live"])
args = parser.parse_args()
commands = (
    [["make", "test"]]
    if args.phase == "checks"
    else [["make", "smoke"], ["make", "browser"], ["make", "audit"], ["make", "eval"], ["make", "cleanup"]]
)
results = ROOT / "docs/mvp/results"
results.mkdir(parents=True, exist_ok=True)
revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
manifest = []
for command in commands:
    name = command[-1]
    log = results / f"final-{name}.log"
    start = datetime.now(timezone.utc).isoformat()
    with log.open("w") as output:
        status = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT).returncode
    row = dict(command=" ".join(command), exit_code=status, revision=revision, start_utc=start, log=log.name)
    manifest.append(row)
    (results / f"{args.phase}-commands.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{row['command']}: exit {status} ({log.relative_to(ROOT)})", flush=True)
    if status:
        print(log.read_text()[-7000:])
        raise SystemExit(status)
