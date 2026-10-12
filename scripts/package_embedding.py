"""Build-time download of exact public model artifacts, verified before use."""

import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen

manifest = json.loads(Path("infra/embedding-manifest.json").read_text())
target = Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
for name, expected in manifest["files"].items():
    url = f"https://huggingface.co/{manifest['repository']}/resolve/{manifest['revision']}/{name}"
    data = urlopen(url, timeout=120).read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Embedding artifact checksum mismatch: {name}")
    (target / name).write_bytes(data)
print("Verified all pinned embedding artifacts")
