"""Shared source authorization for retrieval, pinned workflows and source viewers."""

from .config import settings


def audiences_for(user=None):
    # Never derive campus affiliation from a user message or the model.
    granted = (user or {}).get("knowledge_audiences", [])
    return ["campus", *sorted(set(granted) & {"student", "staff"})]


def access_params(audiences=None):
    return dict(
        access_mode=settings().app_mode,
        grounded=settings().agent_mode == "grounded",
        audiences=audiences or ["campus"],
    )


# Queries using this predicate must join articles a, sections s and corpora c.
ACCESS_SQL = """
    c.withdrawn_at IS NULL AND a.withdrawn_at IS NULL
    AND (a.review_due IS NULL OR a.review_due >= CURRENT_DATE)
    AND (
      (%(access_mode)s='demo' AND a.is_synthetic AND a.allowed_visibility='local demo')
      OR
      (%(access_mode)s='pilot' AND a.audiences ?| %(audiences)s::text[] AND (
        (a.is_synthetic AND a.allowed_visibility='private synthetic pilot'
          AND (s.workflow_version IS NOT NULL OR %(grounded)s))
        OR (NOT a.is_synthetic AND a.allowed_visibility='campus pilot' AND %(grounded)s)
      ))
    )
"""


def withdraw(conn, version, source_id=None):
    """Operator-only, irreversible through this API; reissue content as a new version."""
    if source_id:
        return conn.execute(
            "UPDATE articles SET withdrawn_at=COALESCE(withdrawn_at,now()) WHERE corpus_version=%s AND id=%s",
            (version, source_id),
        ).rowcount
    return conn.execute(
        "UPDATE corpora SET withdrawn_at=COALESCE(withdrawn_at,now()) WHERE version=%s", (version,)
    ).rowcount


if __name__ == "__main__":
    import argparse
    from .db import connection

    parser = argparse.ArgumentParser(
        description="Withdraw reviewed knowledge from retrieval and source viewing"
    )
    parser.add_argument("version")
    parser.add_argument("--source-id")
    args = parser.parse_args()
    with connection() as conn:
        print({"withdrawn": withdraw(conn, args.version, args.source_id)})
