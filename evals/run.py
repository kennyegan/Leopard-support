"""Frozen synthetic pilot via real HTTP. Metrics are oracle checks, not human adjudication."""

import csv
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    data = (ROOT / "evals/cases.json").read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == (ROOT / "evals/FROZEN.sha256").read_text().split()[0], "Frozen cases changed"
    cases = json.loads(data)["cases"]
    assert len(cases) == 20 and sum(c["complete"] for c in cases) == 10
    rows = []
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30) as client:
        health = client.get("/health").json()
        assert health["provider"] == "scripted" and health["external_ai_enabled"] is False, (
            "Pilot must not cause external AI usage"
        )
        for case in cases:
            for mode in ("policy", "baseline"):
                r = client.post("/api/sessions", json={"mode": mode})
                r.raise_for_status()
                sid = r.json()["id"]
                turns = []
                # Identical scripted user inputs for both modes, including follow-ups.
                for text in [case["initial"]] + case["followups"]:
                    start = time.perf_counter()
                    r = client.post(f"/api/sessions/{sid}/messages", json={"text": text})
                    r.raise_for_status()
                    turns.append(
                        {"input": text, "response": r.json(), "seconds": time.perf_counter() - start}
                    )
                snaps = client.get(f"/api/sessions/{sid}/snapshots").json()
                first, last = turns[0]["response"], turns[-1]["response"]
                final_guides = {s["id"] for s in last["sources"]}
                correct = last["action"] == case["expected_final"] and (
                    not case["gold_guides"] or bool(final_guides & set(case["gold_guides"]))
                )
                wrong_answers = sum(
                    t["response"]["action"] == "ANSWER"
                    and (
                        not case["gold_guides"]
                        or not ({s["id"] for s in t["response"]["sources"]} & set(case["gold_guides"]))
                        or (i == 0 and case["expected_first"] == "ASK")
                    )
                    for i, t in enumerate(turns)
                )
                grounded = []
                for t in turns:
                    a = t["response"]
                    if a["action"] == "ANSWER" and a["sources"]:
                        source = client.get("/api/guides/" + a["sources"][0]["id"]).json()
                        allowed = [step for s in source for step in s["steps"]]
                        grounded.extend(step in allowed for step in a["steps"])
                top3 = {g["source_id"] for g in snaps[-1]["retrieval"][:3]}
                useful_questions = 0
                question_count = 0
                for index, item in enumerate(turns):
                    answer = item["response"]
                    if answer["action"] != "ASK":
                        continue
                    question_count += 1
                    if index + 1 < len(turns):
                        field = answer["question_field"]
                        following = turns[index + 1]["response"]["state"]
                        useful_questions += bool(
                            following["category"] if field == "category" else following["details"].get(field)
                        )
                rows.append(
                    dict(
                        case=case["id"],
                        mode=mode,
                        session_id=sid,
                        complete=case["complete"],
                        correct_final=correct,
                        correct_first=first["action"] == case["expected_first"],
                        unnecessary_asks=sum(t["response"]["action"] == "ASK" for t in turns)
                        if case["complete"]
                        else 0,
                        oracle_wrong_answer_turns=wrong_answers,
                        recall_at_3=bool(top3 & set(case["gold_guides"])) if case["gold_guides"] else None,
                        useful_question_proxy=useful_questions,
                        question_count=question_count,
                        weak_match_answers=sum(
                            t["response"]["action"] == "ANSWER"
                            and bool(t["response"]["sources"])
                            and t["response"]["sources"][0]["score"] < 0.55
                            for t in turns
                        ),
                        unsupported_answers=sum(t["response"]["action"] == "ANSWER" for t in turns)
                        if not case["gold_guides"]
                        else 0,
                        exact_source_steps=sum(grounded),
                        answer_steps=len(grounded),
                        turns=turns,
                        snapshots=snaps,
                        human_adjudication="pending",
                    )
                )
    out = ROOT / os.environ.get("EVAL_OUTPUT", "evals/results")
    out.mkdir(parents=True, exist_ok=True)
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError:
        revision = "uncommitted"
    summary = {}
    for mode in ("policy", "baseline"):
        selected = [r for r in rows if r["mode"] == mode]
        recall = [r["recall_at_3"] for r in selected if r["recall_at_3"] is not None]
        latencies = [t["seconds"] for r in selected for t in r["turns"]]
        summary[mode] = dict(
            correct_final=sum(r["correct_final"] for r in selected),
            cases=20,
            correct_first=sum(r["correct_first"] for r in selected),
            oracle_wrong_answer_turns=sum(r["oracle_wrong_answer_turns"] for r in selected),
            unnecessary_asks=sum(r["unnecessary_asks"] for r in selected),
            complete_cases=10,
            recall_at_3_numerator=sum(recall),
            recall_at_3_denominator=len(recall),
            useful_question_proxy=sum(r["useful_question_proxy"] for r in selected),
            question_count=sum(r["question_count"] for r in selected),
            weak_match_answers=sum(r["weak_match_answers"] for r in selected),
            unsupported_answers=sum(r["unsupported_answers"] for r in selected),
            exact_source_steps=sum(r["exact_source_steps"] for r in selected),
            answer_steps=sum(r["answer_steps"] for r in selected),
            mean_turns=sum(len(r["turns"]) for r in selected) / 20,
            mean_reply_seconds=sum(latencies) / len(latencies),
            max_reply_seconds=max(latencies),
        )
    (out / "traces.json").write_text(
        json.dumps(
            dict(revision=revision, cases_sha256=digest, health=health, summary=summary, results=rows),
            indent=2,
        )
    )
    scalar = [{k: v for k, v in r.items() if k not in ("turns", "snapshots")} for r in rows]
    with (out / "outcomes.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(scalar[0]))
        writer.writeheader()
        writer.writerows(scalar)
    lines = [
        "# Frozen 20-case synthetic pilot",
        "",
        f"Tested code revision: `{revision}`. Case SHA-256: `{digest}`.",
        "",
        "Same scripted offline interpreter, corpus, embedding model, retrieval code and user turns in both modes. No external LLM calls.",
        "",
        "| Metric | Policy | Baseline |",
        "|---|---:|---:|",
    ]
    for key in summary["policy"]:
        lines.append(f"| {key} | {summary['policy'][key]} | {summary['baseline'][key]} |")
    lines += [
        "",
        "## Interpretation and manual review",
        "Correctness is measured against predeclared synthetic guide/outcome oracles. The wrong-answer proxy counts answers with wrong/no gold guides and answers before a required discriminator is supplied. It is not independent adjudication of confident wrong answers.",
        "Exact-source step membership verifies verbatim rendering, not real-world troubleshooting correctness. Human review of applicability, grounded meaning, and useful questions remains pending for every case.",
        "Useful-question proxy counts questions whose next scripted reply supplies the requested field; it is not a human usefulness rating.",
        "Recall@3 is reported on the final scripted query for cases with a gold guide. Mean turns counts replayed user turns, not verified real-user resolution. Both modes receive identical follow-ups, even if baseline already answered.",
        "This 20-case fictional pilot validates the harness, not the official 60-case study or population-level effectiveness. Thresholds remain provisional raw cosine .75/.55; no holdout tuning.",
    ]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
