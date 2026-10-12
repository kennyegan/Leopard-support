from functools import lru_cache
from fastembed import TextEmbedding
from psycopg.types.json import Jsonb
from .config import settings
from .models import Guide, State
from .graph import matches

MODEL = "BAAI/bge-small-en-v1.5"
CORPUS = "synthetic-2026-10-v1"


def corpus_version():
    return settings().corpus_version


@lru_cache
def embedder():
    cfg = settings()
    return TextEmbedding(
        model_name=MODEL,
        cache_dir=cfg.embed_cache,
        threads=2,
        specific_model_path=cfg.embed_model_path or None,
        local_files_only=bool(cfg.embed_model_path),
    )


def vector_literal(vector):
    return "[" + ",".join(str(float(x)) for x in vector) + "]"


def row_guide(row):
    return Guide(
        id=row["id"],
        source_id=row["article_id"],
        title=row["title"],
        category=row["category"],
        source_url=row["source_url"],
        corpus_version=row["corpus_version"],
        is_synthetic=row["is_synthetic"],
        heading=row["heading"],
        section_text=row["section_text"],
        steps=row["steps"],
        applicability=row["applicability"],
        request_types=row["request_types"],
        references=row["reference_links"],
        workflow=row["workflow"],
        workflow_version=row["workflow_version"],
        intake=row["intake"],
        routing=row["routing"],
        score=float(row.get("score", 0)),
    )


def retrieve(conn, text: str, state: State, *, ranking=None) -> list[Guide]:
    facts = " ".join(v for v in state.details.model_dump().values() if v)
    query = f"{state.problem_text} {text} {facts}"[:2500]
    if settings().dialogue_mode == "conversational":
        query = f"{state.request_type} {query}"
    vector = vector_literal(next(embedder().query_embed(query)))
    if settings().app_mode == "pilot":
        # Exclude inaccessible or contradicted candidates BEFORE ranking/top-k.
        # Missing facts remain eligible for source-backed intake, never guessed.
        rows = conn.execute(
            """
          SELECT s.*, a.title,a.category,a.source_url,a.is_synthetic,
                 1-(s.embedding <=> %(vector)s::vector) AS score,
                 ts_rank_cd(to_tsvector('simple',a.title || ' ' || s.section_text),
                            plainto_tsquery('simple',%(query)s)) AS lexical
          FROM sections s JOIN articles a ON a.id=s.article_id AND a.corpus_version=s.corpus_version
          WHERE s.corpus_version=%(corpus)s AND a.allowed_visibility='private synthetic pilot'
            AND a.is_synthetic AND s.workflow_version IS NOT NULL
            AND (%(category)s::text IS NULL OR a.category=%(category)s)
            AND s.request_types ? %(request)s
            AND NOT EXISTS (SELECT 1 FROM jsonb_each_text(s.applicability) p
                WHERE p.value <> 'any' AND %(facts)s::jsonb ->> p.key IS NOT NULL
                  AND %(facts)s::jsonb ->> p.key <> p.value)
          ORDER BY s.embedding <=> %(vector)s::vector,s.id
        """,
            dict(
                vector=vector,
                query=query,
                corpus=corpus_version(),
                category=state.category,
                request=state.request_type,
                facts=Jsonb(state.details.model_dump()),
            ),
        ).fetchall()
        # Exact scan is bounded by the reviewed corpus. Hybrid ranking is opt-in
        # until evaluated; cosine remains a similarity, never a probability.
        if (ranking or settings().retrieval_ranking) == "hybrid":
            dense_rank = {r["id"]: i + 1 for i, r in enumerate(rows)}
            lexical_rank = {
                r["id"]: i + 1
                for i, r in enumerate(
                    sorted((r for r in rows if r["lexical"] > 0), key=lambda r: (-r["lexical"], r["id"]))
                )
            }
            rows.sort(
                key=lambda r: (
                    -(
                        1 / (60 + dense_rank[r["id"]])
                        + (1 / (60 + lexical_rank[r["id"]]) if r["id"] in lexical_rank else 0)
                    ),
                    r["id"],
                )
            )
        rows = [
            r
            for r in rows
            if r["article_id"] not in state.attempted_guides + state.completed_guides
            and matches(row_guide(r), state)
        ]
        # Ready-to-use evidence should not be crowded out by five guides that
        # still need a discriminator. Preserve the ranking within each group.
        rows.sort(
            key=lambda r: any(
                v != "any" and getattr(state.details, k) is None for k, v in r["applicability"].items()
            )
        )
        rows = rows[:5]
    else:
        rows = conn.execute(
            """
          SELECT s.*,a.title,a.category,a.source_url,a.is_synthetic,1-(s.embedding <=> %s::vector) AS score
          FROM sections s JOIN articles a ON a.id=s.article_id AND a.corpus_version=s.corpus_version
          WHERE s.corpus_version=%s AND (%s OR s.request_types ? %s)
          ORDER BY s.embedding <=> %s::vector,s.id LIMIT 5
        """,
            (vector, corpus_version(), settings().dialogue_mode == "classic", state.request_type, vector),
        ).fetchall()
    return [row_guide(row) for row in rows]


def load_guide(conn, source_id, *, version=None, section_id=None, workflow_version=None):
    row = conn.execute(
        """
      SELECT s.*,a.title,a.category,a.source_url,a.is_synthetic
      FROM sections s JOIN articles a ON a.id=s.article_id AND a.corpus_version=s.corpus_version
      WHERE s.article_id=%s AND s.corpus_version=%s
        AND (%s::text IS NULL OR s.id=%s)
        AND (%s::text IS NULL OR s.workflow_version=%s)
        AND (%s OR (a.allowed_visibility='private synthetic pilot' AND a.is_synthetic AND s.workflow_version IS NOT NULL))
      ORDER BY s.chunk_index LIMIT 1
    """,
        (
            source_id,
            version or corpus_version(),
            section_id,
            section_id,
            workflow_version,
            workflow_version,
            settings().app_mode != "pilot",
        ),
    ).fetchone()
    return row_guide(row) if row else None


def load_active(conn, state):
    if not state.active_guide:
        return None
    if settings().app_mode == "pilot" and not all(
        (state.active_corpus, state.active_section, state.active_workflow_version)
    ):
        return None
    return load_guide(
        conn,
        state.active_guide,
        version=state.active_corpus,
        section_id=state.active_section,
        workflow_version=state.active_workflow_version,
    )
