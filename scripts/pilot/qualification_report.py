"""Attach durable provider telemetry to completed, immutable v2 HTTPS runs."""

import hashlib
import json
import math
from decimal import Decimal
from uuid import UUID

from operations import ROOT, sql


def main():
    results = ROOT / "docs/pilot/results"
    names = [
        "conversations-live-v2-holdout.json",
        "conversations-live-v2-repeat-2.json",
        "conversations-live-v2-repeat-3.json",
    ]
    report = {
        "scope": "Local synthetic v4; final-candidate v2 qualification",
        "provider_parameters": {
            "temperature": 0,
            "max_tokens": 1600,
            "reasoning_enabled": False,
            "require_parameters": True,
            "allow_fallbacks": False,
            "data_collection": "deny",
            "zdr": True,
            "max_price": {"prompt": 1, "completion": 5, "request": 0},
        },
        "parameter_source_sha256": hashlib.sha256((ROOT / "apps/api/app/llm.py").read_bytes()).hexdigest(),
        "runs": [],
    }
    for name in names:
        path = results / name
        data = json.loads(path.read_text())
        assert "summary" in data and not data.get("aborted"), "Incomplete run retained; cannot qualify"
        turns = [t for c in data["cases"] for t in c["turns"]]
        ids = [str(UUID(t["reply"]["turn_id"])) for t in turns]
        quoted = ",".join("'" + value + "'" for value in ids)
        records = json.loads(
            sql(
                "SELECT json_agg(row_to_json(t)) FROM (SELECT id,status,error_code,provider,usage "
                f"FROM pilot_turns WHERE id IN ({quoted}) ORDER BY created_at,id) t"
            )
        )
        assert len(records) == len(ids) and all(r["status"] == "completed" for r in records)
        times = sorted(t["elapsed_ms"] for t in turns)
        usage = [r["usage"] or {} for r in records]
        run = {
            "file": name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "suite_sha256": data["suite_sha256"],
            "health": data["health_manifest"],
            "summary": data["summary"],
            "user_turns": len(turns),
            "https_latency_ms": {f"p{p}": times[math.ceil(len(times) * p / 100) - 1] for p in (50, 95, 99)},
            "provider_calls": data["budget_after"]["calls"] - data["budget_before"]["calls"],
            "provider_reservation_usd": str(
                Decimal(str(data["budget_after"]["reserved_usd"]))
                - Decimal(str(data["budget_before"]["reserved_usd"]))
            ),
            "provider_reported_cost_usd": str(
                sum((Decimal(str(u.get("cost", 0))) for u in usage), Decimal(0))
            ),
            "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usage),
            "completion_tokens": sum(u.get("completion_tokens", 0) for u in usage),
            "models": sorted({u["model"] for u in usage if "model" in u}),
            "revisions": {
                field: sorted({t["reply"][field] for t in turns if t["reply"].get(field)})
                for field in (
                    "application_revision",
                    "skill_version",
                    "interpretation_schema",
                    "corpus_version",
                )
            },
            "turn_telemetry": records,
        }
        report["runs"].append(run)
    repeats = json.loads((ROOT / "evals/pilot/REPEATS-V2.json").read_text())["case_ids"]
    report["repeatability"] = {
        key: [
            {
                "trial": data["trial"],
                "end_state": case["end_state"],
                "end_match": case["end_match"],
                "invariant_failures": case["invariant_failures"],
            }
            for name in names
            for data in [json.loads((results / name).read_text())]
            for case in data["cases"]
            if case["id"] == key
        ]
        for key in repeats
    }
    report["independent_human_review"] = "pending; automated success is not a usefulness rating"
    target = results / "qualification-v2-report.json"
    if target.exists():
        raise SystemExit("Refusing to overwrite existing qualification report")
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "runs": [
                    {k: v for k, v in r.items() if k not in ("turn_telemetry", "health")}
                    for r in report["runs"]
                ]
            }
        )
    )


if __name__ == "__main__":
    main()
