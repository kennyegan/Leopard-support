"""Local full stack runner. Ctrl-C terminates owned API/web processes, preserves DB."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
subprocess.run(["docker", "compose", "-f", "infra/compose.yaml", "up", "-d", "--wait"], check=True)
env = {**os.environ, "PYTHONPATH": str(root / "apps/api"), "TOKENIZERS_PARALLELISM": "false"}
subprocess.run([sys.executable, "-m", "app.ingest"], env=env, check=True)
processes = []
try:
    processes.append(
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            env=env,
            start_new_session=True,
        )
    )
    processes.append(
        subprocess.Popen(
            ["npm", "run", "start" if os.environ.get("TECHSPOT_WEB_MODE") == "production" else "dev"],
            cwd=root / "apps/web",
            env={**env, "NEXT_TELEMETRY_DISABLED": "1"},
            start_new_session=True,
        )
    )
    print(
        "TechSpot Assist: http://127.0.0.1:3000 — synthetic demo; interpreter configuration at /api/health",
        flush=True,
    )
    while all(p.poll() is None for p in processes):
        time.sleep(0.5)
except KeyboardInterrupt:
    pass
finally:
    for p in processes:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGTERM)
    for p in processes:
        p.wait(timeout=10)
