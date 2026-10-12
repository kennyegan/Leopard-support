"""Scan local image archives with networking disabled; never upload an image."""

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SCANNER = "aquasec/trivy:0.69.3@sha256:bcc376de8d77cfe086a917230e818dc9f8528e3c852f7b1aff648949b6258d1c"
for service in ["api", "web"]:
    archive = ROOT / f".runtime/pilot/{service}-image.tar"
    subprocess.run(
        ["docker", "save", "-o", str(archive), "techspot-" + service + ":pilot-candidate"], check=True
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            str(ROOT / ".runtime/pilot/trivy-cache") + ":/root/.cache/trivy",
            "-v",
            str(archive) + ":/image.tar:ro",
            "-v",
            str(ROOT / "docs/pilot/results") + ":/results",
            SCANNER,
            "image",
            "--input",
            "/image.tar",
            "--offline-scan",
            "--skip-db-update",
            "--skip-java-db-update",
            "--scanners",
            "vuln",
            "--no-progress",
            "--format",
            "json",
            "--output",
            f"/results/{service}-image.json",
        ],
        check=True,
    )
    data = json.loads((ROOT / f"docs/pilot/results/{service}-image.json").read_text())
    high = [
        dict(
            id=v["VulnerabilityID"],
            package=v["PkgName"],
            installed=v["InstalledVersion"],
            fixed=v.get("FixedVersion", ""),
            severity=v["Severity"],
        )
        for r in data.get("Results", [])
        for v in r.get("Vulnerabilities", [])
        if v["Severity"] in ["HIGH", "CRITICAL"]
    ]
    print(
        json.dumps(
            dict(
                image=service,
                network="none",
                high_critical=len(high),
                critical=sum(v["severity"] == "CRITICAL" for v in high),
                fixable=sum(bool(v["fixed"]) for v in high),
            )
        ),
        flush=True,
    )
    if any(v["fixed"] for v in high):
        raise SystemExit("Fixable high/critical image vulnerabilities remain; see the full report")
