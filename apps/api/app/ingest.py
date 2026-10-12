"""Explicit import path. No crawling. Synthetic-only anonymous MVP corpus."""

import csv
import hashlib
import json
import re
from urllib.parse import urlparse
from html.parser import HTMLParser
from pathlib import Path
from psycopg.types.json import Jsonb
from .config import ROOT, settings
from .db import connection, migrate
from .models import Guide
from .graph import validate_graph
from .privacy import redact
from .retrieval import MODEL, embedder, vector_literal


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("h1", "h2", "h3"):
            self.parts.append("\n## ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("p", "h1", "h2", "h3", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def sections_from_html(html):
    parser = PlainHTML()
    parser.feed(html)
    chunks = []
    for part in "".join(parser.parts).split("## "):
        lines = part.strip().splitlines()
        if not lines:
            continue
        heading, content = lines[0], " ".join(lines[1:])
        words = (content or heading).split()
        for offset in range(0, len(words), 300):
            chunks.append({"heading": heading, "text": " ".join(words[offset : offset + 300])})
    return chunks


def load(path: Path):
    if path.suffix == ".json":
        return json.loads(path.read_text())
    metadata = json.loads(path.with_suffix(".metadata.json").read_text())
    if path.suffix == ".csv":
        with path.open() as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            row["applicability"] = json.loads(row["applicability"])
            row["sections"] = json.loads(row["sections"])
            row["is_synthetic"] = row["is_synthetic"].lower() == "true"
        metadata["guides"] = rows
    elif path.suffix in (".html", ".htm"):
        guide = metadata.pop("guide")
        sections = sections_from_html(path.read_text())
        steps_by_heading = guide.pop("steps_by_heading", {})
        for section in sections:
            if section["heading"] not in steps_by_heading:
                raise ValueError("HTML import needs reviewed steps_by_heading metadata")
            section["steps"] = steps_by_heading[section["heading"]]
        guide["sections"] = sections
        metadata["guides"] = [guide]
    else:
        raise ValueError("Supported formats: JSON, CSV or HTML with permission metadata")
    return metadata


def ingest(path=None):
    if path is None:
        filename = {
            "synthetic-2026-10-v1": "corpus.json",
            "synthetic-2026-10-v2": "conversational.json",
            "synthetic-2026-10-v3": "diagnostic.json",
            "synthetic-2026-10-v4": "pilot.json",
        }[settings().corpus_version]
        path = ROOT / "fixtures/synthetic_guides" / filename
    corpus = load(Path(path))
    permission = corpus["permission"]
    if permission.get("audience") not in {"local demo", "private synthetic pilot"} or not permission.get(
        "approved_by"
    ):
        raise ValueError("Explicit local-demo permission required")
    digest = hashlib.sha256(json.dumps(corpus, sort_keys=True).encode()).hexdigest()
    records = []
    for article in corpus["guides"]:
        if not article.get("is_synthetic") or article["source_url"] != "demo://" + article["id"]:
            raise ValueError("This anonymous MVP import accepts synthetic local sources only")
        for index, section in enumerate(article["sections"]):
            raw = (
                section["text"]
                + " ".join(section["steps"])
                + json.dumps(
                    {"workflow": section.get("workflow", []), "intake": article.get("intake", [])},
                    ensure_ascii=False,
                )
            )
            if redact(raw) != raw or re.search(
                r"ignore (?:all |previous |system )*instructions|system prompt|exfiltrat", raw, re.I
            ):
                raise ValueError("Unsafe guide content requires review")
            g = Guide(
                id=f"{article['id']}:{index}",
                source_id=article["id"],
                title=article["title"],
                category=article["category"],
                source_url=article["source_url"],
                corpus_version=corpus["version"],
                heading=section["heading"],
                section_text=section["text"],
                steps=section["steps"],
                applicability=article["applicability"],
                request_types=article.get("request_types", ["troubleshoot"]),
                references=article.get("references", []),
                workflow=section.get("workflow", []),
                workflow_version=section.get("workflow_version"),
                intake=article.get("intake", []),
                routing=article.get("routing", {}),
            )
            validate_graph(g)
            if permission["audience"] == "private synthetic pilot" and not g.workflow_version:
                raise ValueError("Pilot sources require a validated diagnostic graph")
            for ref in g.references:
                url = urlparse(ref.url)
                if (
                    url.scheme != "https"
                    or url.hostname not in {"www.autodesk.com", "manage.autodesk.com", "help.autodesk.com"}
                    or url.username
                    or url.password
                ):
                    raise ValueError("Unreviewed reference host")
            if any(i < 0 or i >= len(g.steps) for w in g.workflow for i in w.indexes):
                raise ValueError("Workflow references nonexistent source steps")
            records.append((g, index))
    migrate()
    with connection() as conn:
        old = conn.execute(
            "SELECT content_hash FROM corpora WHERE version=%s", (corpus["version"],)
        ).fetchone()
        if old:
            if old["content_hash"] != digest:
                raise ValueError("Existing corpus versions are immutable: increment the version")
            return {"version": corpus["version"], "sections": len(records), "unchanged": True, "hash": digest}
        vectors = list(
            embedder().passage_embed(
                [f"{g.title}. {g.section_text} " + " ".join(g.steps) for g, _ in records]
            )
        )
        conn.execute(
            "INSERT INTO corpora(version,content_hash,model,permission) VALUES(%s,%s,%s,%s)",
            (corpus["version"], digest, MODEL, Jsonb(permission)),
        )
        for (g, index), vector in zip(records, vectors, strict=True):
            content_hash = hashlib.sha256(g.model_dump_json().encode()).hexdigest()
            conn.execute(
                """INSERT INTO articles(id,corpus_version,title,category,source_url,is_synthetic,allowed_visibility,content_hash)
              VALUES(%s,%s,%s,%s,%s,true,%s,%s) ON CONFLICT DO NOTHING""",
                (
                    g.source_id,
                    g.corpus_version,
                    g.title,
                    g.category,
                    g.source_url,
                    permission["audience"],
                    content_hash,
                ),
            )
            conn.execute(
                """INSERT INTO sections(id,corpus_version,article_id,heading,section_text,steps,embedding,applicability,chunk_index,content_hash,request_types,reference_links,workflow,workflow_version,intake,routing)
              VALUES(%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    g.id,
                    g.corpus_version,
                    g.source_id,
                    g.heading,
                    g.section_text,
                    Jsonb(g.steps),
                    vector_literal(vector),
                    Jsonb(g.applicability),
                    index,
                    content_hash,
                    Jsonb(g.request_types),
                    Jsonb([r.model_dump() for r in g.references]),
                    Jsonb([w.model_dump() for w in g.workflow]),
                    g.workflow_version,
                    Jsonb([q.model_dump() for q in g.intake]),
                    Jsonb(g.routing),
                ),
            )
    return {
        "version": corpus["version"],
        "sections": len(records),
        "unchanged": False,
        "hash": digest,
        "model": MODEL,
    }


if __name__ == "__main__":
    import sys

    print(json.dumps(ingest(Path(sys.argv[1]) if len(sys.argv) > 1 else None)))
