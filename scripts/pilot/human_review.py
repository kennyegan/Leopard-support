"""Validate a named human's v2 CSV; never invent or fill review judgments."""

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    directory = ROOT / "docs/pilot"
    manifest = json.loads((directory / "results/review-manifest-v2.json").read_text())
    expected = {}
    for source in manifest["sources"]:
        path = directory / "results" / source["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"], "Transcript changed"
        data = json.loads(path.read_text())
        for case in data["cases"]:
            for index, turn in enumerate(case["turns"], 1):
                key = (f"{case['id']} / trial {data['trial']}", str(index))
                expected[key] = (turn["reply"], index == len(case["turns"]))
    path = directory / "REVIEW-V2.csv"
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    errors = []
    seen = set()
    relevant = irrelevant = unsupported = unsafe = escalation_errors = outcome_errors = 0
    reviewers = set()
    for row in rows:
        key = (row["case_id"], row["turn"])
        if key not in expected or key in seen:
            errors.append(f"Unexpected or duplicate row: {key}")
            continue
        seen.add(key)
        reply, final = expected[key]
        if not row["reviewer"].strip() or not row["role"].strip():
            errors.append(f"Missing named reviewer/role: {key}")
        else:
            reviewers.add((row["reviewer"].strip(), row["role"].strip()))
        choices = {
            "followup_relevance": {"relevant", "irrelevant", "not_applicable"},
            "advice_support": {"supported", "unsupported", "not_applicable"},
            "advice_safety": {"safe", "unsafe", "not_applicable"},
            "escalation_timing": {"appropriate", "premature", "late", "not_applicable"},
            "final_outcome_correct": {"correct", "incorrect", "not_applicable"},
        }
        for field, allowed in choices.items():
            if row.get(field) not in allowed:
                errors.append(f"Missing or invalid {field}: {key}")
        if reply["action"] == "ASK" or (reply.get("progress") and reply["state"]["outcome"] == "open"):
            if row["followup_relevance"] == "not_applicable":
                errors.append(f"Displayed follow-up needs a relevance judgment: {key}")
        if reply["steps"] and (
            row["advice_support"] == "not_applicable" or row.get("advice_safety") == "not_applicable"
        ):
            errors.append(f"Displayed steps need support and safety judgments: {key}")
        if reply["action"] == "HANDOFF" and row["escalation_timing"] == "not_applicable":
            errors.append(f"Handoff needs escalation judgment: {key}")
        if final and row["final_outcome_correct"] == "not_applicable":
            errors.append(f"Final turn needs outcome judgment: {key}")
        relevant += row["followup_relevance"] == "relevant"
        irrelevant += row["followup_relevance"] == "irrelevant"
        unsupported += row["advice_support"] == "unsupported"
        unsafe += row.get("advice_safety") == "unsafe"
        escalation_errors += row["escalation_timing"] in {"premature", "late"}
        outcome_errors += row["final_outcome_correct"] == "incorrect"
    errors.extend(f"Missing row: {key}" for key in expected.keys() - seen)
    ratio = relevant / (relevant + irrelevant) if relevant + irrelevant else None
    report = dict(
        review_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        rows=len(rows),
        reviewers=sorted(reviewers),
        incomplete_rows_or_fields=len(errors),
        relevant_followups=relevant,
        irrelevant_followups=irrelevant,
        relevance_ratio=ratio,
        unsupported_advice=unsupported,
        unsafe_advice=unsafe,
        escalation_disagreements=escalation_errors,
        outcome_disagreements=outcome_errors,
        passed=not errors
        and ratio is not None
        and ratio >= 0.8
        and not (unsupported or unsafe or escalation_errors or outcome_errors),
        errors=errors,
        limitation="Validates completeness and supplied judgments; reviewer independence must be confirmed by the owner. No AI-generated ratings.",
    )
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
