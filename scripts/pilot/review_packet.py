"""Render synthetic transcripts for independent human qualification; never auto-score relevance."""

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/pilot"
parser = argparse.ArgumentParser()
parser.add_argument("--suite", choices=["v1", "v2"], default="v1")
args = parser.parse_args()
suffix = "-V2" if args.suite == "v2" else ""
sources = [
    "conversations-live-development.json",
    "conversations-live-development-recheck.json",
    "conversations-live-holdout.json",
]
if args.suite == "v2":
    sources = [
        "conversations-live-v2-holdout.json",
        "conversations-live-v2-repeat-2.json",
        "conversations-live-v2-repeat-3.json",
    ]
corpus_path = ROOT / "fixtures/synthetic_guides/pilot.json"
corpus = json.loads(corpus_path.read_text())
guide_index = {guide["id"]: guide for guide in corpus["guides"]}
cases = {}
manifest = []
for name in sources:
    path = OUT / "results" / name
    if not path.exists():
        if args.suite == "v2":
            raise SystemExit("Final v2 packet requires all three completed runs")
        continue
    data = json.loads(path.read_text())
    if args.suite == "v2" and ("summary" not in data or data.get("aborted")):
        raise SystemExit("Final v2 packet requires complete, non-aborted runs")
    manifest.append(dict(file=name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    for case in data["cases"]:
        key = case["id"] if args.suite == "v1" else f"{case['id']} / trial {data['trial']}"
        cases[key] = {**case, "review_id": key}

escape = html.escape
parts = [
    '<!doctype html><html lang="en"><meta charset="utf-8"><title>TechSpot independent review</title>',
    "<style>body{font:17px system-ui;max-width:900px;margin:40px auto;padding:16px;line-height:1.5}article{border-top:2px solid #777;margin-top:40px}section{padding:14px;margin:8px 0;background:#f4f6fa}small{color:#444}pre{white-space:pre-wrap}li{margin:6px}</style>",
    "<h1>Independent conversation review</h1><p>Synthetic local qualification. Automated end-state and source checks do not score usefulness.</p>",
    "<p>Review the whole trajectory, including whether the next scripted user reply naturally answers the preceding question. Label each follow-up relevant/irrelevant, each advice supported/unsupported and safe/unsafe, escalation appropriate/premature/late, and final task outcome correct/incorrect. Record reviewer identity/role and disagreements in the companion REVIEW CSV. For v2, mark non-applicable judgments not_applicable; blank cells mean incomplete review. Do not claim device success from a user report alone.</p>",
]
rows = []
for case in cases.values():
    parts.append(
        f"<article><h2>{escape(case['review_id'])}</h2><p>{escape(str(case.get('review_rubric', '')))}</p>"
    )
    for index, turn in enumerate(case["turns"], 1):
        reply = turn.get("reply", {})
        parts.append(
            f"<section><b>User {index}</b><p>{escape(turn['user'])}</p><b>Assistant</b><p>{escape(reply.get('text', 'HTTP failure'))}</p>"
        )
        if reply.get("steps"):
            parts.append(
                "<ol>" + "".join("<li>" + escape(step) + "</li>" for step in reply["steps"]) + "</ol>"
            )
        if reply.get("progress"):
            parts.append("<p>" + escape(reply["progress"]["prompt"]) + "</p>")
        parts.append("<p>" + escape(" · ".join(reply.get("options", []))) + "</p>")
        if reply.get("warning"):
            parts.append("<p>Warning: " + escape(str(reply["warning"])) + "</p>")
        for reference in reply.get("references", []):
            parts.append("<p>Reference: " + escape(reference["title"] + " — " + reference["url"]) + "</p>")
        parts.append(
            "<small>"
            + escape(" | ".join(source["title"] for source in reply.get("sources", [])))
            + "</small>"
        )
        for source in reply.get("sources", []):
            assert source["corpus_version"] == corpus["version"], "Review requires the exact pinned corpus"
            guide = guide_index[source["id"]]
            section = guide["sections"][int(source["section_id"].rsplit(":", 1)[1])]
            parts.append(
                "<details><summary>Exact synthetic source and workflow: "
                + escape(source["section_id"])
                + "</summary><pre>"
                + escape(json.dumps(section, indent=2, ensure_ascii=False))
                + "</pre></details>"
            )
        if reply.get("ticket"):
            parts.append(
                "<details><summary>Ticket draft</summary><pre>"
                + escape(reply["ticket"]["draft"])
                + "</pre></details>"
            )
        parts.append("</section>")
        rows.append(
            dict(
                case_id=case["review_id"],
                turn=index,
                reviewer="",
                role="",
                followup_relevance="",
                advice_support="",
                advice_safety="",
                escalation_timing="",
                final_outcome_correct="",
                notes="",
            )
        )
    parts.append("</article>")
parts.append("</html>")
(OUT / f"REVIEW{suffix}.html").write_text("\n".join(parts) + "\n")
# Preserve human work if a packet is regenerated.
target = OUT / f"REVIEW{suffix}.csv"
if not target.exists():
    with target.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
(OUT / "results" / f"review-manifest{suffix.lower()}.json").write_text(
    json.dumps(
        dict(
            sources=manifest,
            corpus_sha256=hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
            cases=len(cases),
            turns=len(rows),
            independent_review="pending",
        ),
        indent=2,
    )
    + "\n"
)
print(json.dumps(dict(cases=len(cases), turns=len(rows), independent_review="pending")))
