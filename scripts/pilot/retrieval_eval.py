"""Compare eligible dense/hybrid retrieval with fixed labels; no inference."""

import hashlib
import json
import statistics
import time
from app.config import ROOT, settings
from app.db import connection
from app.ingest import ingest
from app.models import State
from app.retrieval import retrieve

cfg = settings()
cfg.database_url = cfg.database_url.rsplit("/", 1)[0] + "/techspot_test"
cfg.app_mode = "pilot"
cfg.provider = "scripted"
cfg.allow_external_ai = False
cfg.dialogue_mode = "conversational"
cfg.corpus_version = "synthetic-2026-10-v4"
ingest()
path = ROOT / "evals/pilot/retrieval.json"
assert (
    hashlib.sha256(path.read_bytes()).hexdigest() == (path.parent / "RETRIEVAL.sha256").read_text().split()[0]
)
cases = json.loads(path.read_text())
results = []
with connection() as conn:
    for row in cases:
        state = State(
            category=row["category"],
            request_type=row["request_type"],
            details=row["details"],
            problem_text=row["query"],
        )
        for ranking in ["dense", "hybrid"]:
            start = time.perf_counter()
            guides = retrieve(conn, row["query"], state, ranking=ranking)
            rank = next((i + 1 for i, g in enumerate(guides) if g.source_id in row["relevant"]), None)
            results.append(
                dict(
                    id=row["id"],
                    split=row["split"],
                    ranking=ranking,
                    rank=rank,
                    ids=[g.source_id for g in guides],
                    scores=[g.score for g in guides],
                    elapsed_ms=round((time.perf_counter() - start) * 1000),
                )
            )
summary = {}
for split in ["development", "holdout"]:
    for ranking in ["dense", "hybrid"]:
        selected = [r for r in results if r["split"] == split and r["ranking"] == ranking]
        summary[split + "_" + ranking] = dict(
            n=len(selected),
            hit_at_1=sum(r["rank"] == 1 for r in selected) / len(selected),
            hit_at_5=sum(r["rank"] is not None for r in selected) / len(selected),
            mrr=statistics.mean(1 / r["rank"] if r["rank"] else 0 for r in selected),
        )
result = dict(
    corpus=cfg.corpus_version,
    labels_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    summary=summary,
    results=results,
    note="Small implementer-authored exact-identifier comparison; not an independent benchmark. Scores are cosine similarities, not calibrated probabilities.",
)
(ROOT / "docs/pilot/results/retrieval.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(summary))
