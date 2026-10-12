from contextlib import asynccontextmanager
from uuid import UUID, uuid4
import secrets
from collections import defaultdict, deque
import time
from fastapi import FastAPI, HTTPException, Header, Request, Depends
from starlette.middleware.sessions import SessionMiddleware
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg_pool import PoolTimeout, TooManyRequests
from psycopg.types.json import Jsonb
from .config import settings, build_revision
from .db import connection, close_pools
from .llm import ProviderError, provider_configured
from .models import FeedbackIn, MessageIn, SessionIn, State, TicketIn
from .privacy import redact
from .retrieval import MODEL, corpus_version, embedder
from .service import ensure_ticket, turn
from .auth import router as auth_router, principal, authorize_owner
from .boundaries import BodyLimitMiddleware, pilot_access
from .turns import pilot_turn


@asynccontextmanager
async def lifespan(app):
    settings().validate_pilot()
    # Fail visibly if real embedding weights are missing; never silently substitute fake retrieval.
    embedder()
    if settings().app_mode == "pilot":
        with connection() as conn:
            if corpus_sections(conn) == 0:
                raise ValueError(
                    "Pilot requires an ingested corpus with private visibility and validated workflows"
                )
    yield
    close_pools()


app = FastAPI(title="TechSpot Assist — synthetic demo", lifespan=lifespan)
app.include_router(auth_router)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings().session_secret or secrets.token_urlsafe(32),
    session_cookie="__Host-oidc",
    max_age=600,
    same_site="lax",
    https_only=True,
)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings().web_origin],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
)
_limits = defaultdict(deque)


@app.middleware("http")
async def boundaries(request: Request, call_next):
    if settings().app_mode == "pilot":
        try:
            request.state.principal = await run_in_threadpool(pilot_access, request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    try:
        size = int(request.headers.get("content-length", "0"))
    except ValueError:
        return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
    if size > 20000:
        return JSONResponse({"detail": "Request too large"}, status_code=413)
    if settings().app_mode == "demo" and request.method in ("POST", "PUT"):
        key = request.client.host if request.client else "local"
        now = time.monotonic()
        queue = _limits[key]
        while queue and now - queue[0] > 60:
            queue.popleft()
        if len(queue) >= 240:
            return JSONResponse({"detail": "Too many requests. Wait a minute."}, status_code=429)
        queue.append(now)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(OperationalError)
@app.exception_handler(PoolTimeout)
@app.exception_handler(TooManyRequests)
async def db_error(request, exc):
    return JSONResponse({"detail": "Local database unavailable. Please try again."}, status_code=503)


@app.exception_handler(ProviderError)
async def provider_error(request, exc):
    return JSONResponse({"detail": "Interpreter configuration unavailable."}, status_code=503)


def get_session(conn, id, lock=False, user=None):
    row = conn.execute(
        "SELECT * FROM sessions WHERE id=%s" + (" FOR UPDATE" if lock else ""), (id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")
    authorize_owner(row, user)
    if (
        lock
        and settings().app_mode == "pilot"
        and conn.execute(
            "SELECT 1 FROM pilot_turns WHERE session_id=%s AND status='processing' AND lease_expires_at>now()",
            (id,),
        ).fetchone()
    ):
        raise HTTPException(409, "Wait for the current turn before changing this conversation")
    return row


@app.get("/health")
@app.get("/api/health")
def health():
    with connection() as conn:
        count = corpus_sections(conn)
        remaining = None
        if settings().provider != "scripted":
            usage = conn.execute(
                "SELECT calls,authorized_limit,budget_usd,reserved_usd FROM provider_usage WHERE id=1"
            ).fetchone()
            remaining = max(
                0, min(settings().external_call_limit, usage["authorized_limit"]) - usage["calls"]
            )
            if settings().provider == "openrouter" and settings().dialogue_mode == "conversational":
                from decimal import Decimal

                remaining = min(
                    remaining, max(0, int((usage["budget_usd"] - usage["reserved_usd"]) / Decimal("0.033")))
                )
    ready = count >= 12 and provider_configured()
    return JSONResponse(
        dict(
            app_mode=settings().app_mode,
            application_revision=build_revision(),
            qualification_only=settings().pilot_qualification,
            support_contact=settings().pilot_support_contact,
            status=("limited" if remaining == 0 else "ready") if ready else "degraded",
            ai_requests_remaining=remaining,
            database="postgresql/pgvector",
            embedding=MODEL,
            sections=count,
            provider=settings().provider,
            external_ai_enabled=settings().allow_external_ai,
            synthetic=True,
            corpus_version=corpus_version(),
            dialogue_mode=settings().dialogue_mode,
        ),
        status_code=200 if ready else 503,
    )


@app.get("/api/live")
def live():
    return {"alive": True}


@app.get("/api/ready")
def ready():
    with connection() as conn:
        conn.execute("SELECT 1 FROM pilot_turns LIMIT 1")
        count = corpus_sections(conn)
    ok = count >= 12 and provider_configured()
    return JSONResponse(
        {
            "ready": ok,
            "inference_enabled": settings().inference_enabled,
            "provider_health": "configuration_only",
        },
        status_code=200 if ok else 503,
    )


@app.post("/api/sessions", status_code=201)
def create_session(body: SessionIn, user=Depends(principal)):
    if settings().app_mode == "pilot" and body.mode != "policy":
        raise HTTPException(403, "Research mode is unavailable in the pilot")
    id = uuid4()
    with connection() as conn:
        conn.execute(
            "INSERT INTO sessions(id,mode,state,owner_id) VALUES(%s,%s,%s,%s)",
            (id, body.mode, Jsonb(State().model_dump()), user["id"] if user else None),
        )
    return {"id": str(id), "mode": body.mode}


@app.get("/api/sessions/{id}")
def session_history(id: UUID, user=Depends(principal)):
    with connection() as conn:
        session = get_session(conn, id, user=user)
        messages = conn.execute(
            "SELECT id,role,text_redacted AS text,response FROM messages WHERE session_id=%s ORDER BY created_at,role DESC,id",
            (id,),
        ).fetchall()
        ticket = conn.execute(
            "SELECT id,draft_redacted AS draft,edited FROM tickets WHERE session_id=%s AND (problem_id=%s OR problem_id IS NULL) ORDER BY problem_id NULLS LAST LIMIT 1",
            (id, session["state"].get("problem_id")),
        ).fetchone()
        feedback = conn.execute(
            "SELECT message_id,kind,value FROM feedback WHERE session_id=%s", (id,)
        ).fetchall()
        return dict(
            id=str(id),
            mode=session["mode"],
            state=session["state"],
            messages=messages,
            ticket=ticket,
            feedback=feedback,
        )


@app.post("/api/sessions/{id}/messages")
def message(id: UUID, body: MessageIn, user=Depends(principal)):
    if not body.text.strip():
        raise HTTPException(422, "Message cannot be blank")
    if settings().app_mode == "pilot":
        return pilot_turn(id, body, user)
    with connection() as conn:
        session = get_session(conn, id, lock=True, user=user)
        if settings().app_mode == "pilot" and session["mode"] != "policy":
            raise HTTPException(403, "Research mode is unavailable in the pilot")
        if body.request_id:
            previous = conn.execute(
                "SELECT response FROM messages WHERE session_id=%s AND request_id=%s",
                (id, body.request_id),
            ).fetchone()
            if previous:
                if previous["response"] is None:
                    raise HTTPException(410, "This message has expired. Start a new conversation.")
                if previous["response"]["user_message"]["text"] != redact(body.text.strip()):
                    raise HTTPException(409, "Request identifier already used for another message")
                return previous["response"]
        count = conn.execute("SELECT count(*) AS n FROM messages WHERE session_id=%s", (id,)).fetchone()["n"]
        if count >= 100:
            raise HTTPException(429, "Session limit reached. Start a new conversation.")
        result = turn(conn, session, body.text)
        if body.request_id:
            conn.execute("UPDATE messages SET request_id=%s WHERE id=%s", (body.request_id, result["id"]))
        return result


@app.get("/api/sessions/{id}/snapshots")
def snapshots(id: UUID, user=Depends(principal)):
    with connection() as conn:
        get_session(conn, id, user=user)
        return conn.execute(
            "SELECT * FROM state_snapshots WHERE session_id=%s ORDER BY created_at,id", (id,)
        ).fetchall()


@app.delete("/api/sessions/{id}")
def delete_session(id: UUID, user=Depends(principal)):
    if settings().app_mode != "pilot":
        raise HTTPException(403, "Complete deletion is available for owned pilot conversations")
    with connection() as conn:
        get_session(conn, id, lock=True, user=user)
        deleted = conn.execute("SELECT purge_pilot_session(%s,%s) AS deleted", (id, user["id"])).fetchone()
        return {"deleted": deleted["deleted"]}


@app.post("/api/feedback")
def feedback(body: FeedbackIn, user=Depends(principal)):
    try:
        sid, mid, snap = UUID(body.session_id), UUID(body.message_id), UUID(body.snapshot_id)
    except ValueError:
        raise HTTPException(422, "Invalid feedback identifiers") from None
    with connection() as conn:
        session = get_session(conn, sid, lock=True, user=user)
        record = conn.execute(
            "SELECT * FROM state_snapshots WHERE id=%s AND message_id=%s AND session_id=%s", (snap, mid, sid)
        ).fetchone()
        if not record:
            raise HTTPException(404, "Feedback target not found in this session")
        action = record["decision"]["action"]
        original_reply = (
            conn.execute("SELECT response FROM messages WHERE id=%s", (mid,)).fetchone()["response"] or {}
        )
        progress = original_reply.get("progress")
        if body.kind == "fix" and progress and progress["current"] < progress["total"]:
            raise HTTPException(422, "An intermediate step is not task completion")
        if body.kind == "fix" and record["decision"].get("response_kind") == "check":
            raise HTTPException(422, "An observation is not a proposed fix")
        if record["decision"].get("response_kind") in ("explanation", "status", "service_error"):
            raise HTTPException(422, "This message is not a troubleshooting attempt or diagnostic question")
        if (body.kind == "question" and action != "ASK") or (
            body.kind in ("fix", "rating") and action != "ANSWER"
        ):
            raise HTTPException(422, "Feedback kind does not match this message")
        existing = conn.execute(
            "SELECT id,value FROM feedback WHERE message_id=%s AND kind=%s", (mid, body.kind)
        ).fetchone()
        if existing:
            return {"id": str(existing["id"]), "duplicate": True, "value": existing["value"]}
        fid = uuid4()
        conn.execute(
            """INSERT INTO feedback(id,session_id,message_id,state_snapshot_id,kind,value,reason,comment_redacted)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (fid, sid, mid, snap, body.kind, body.value, redact(body.reason), redact(body.comment)),
        )
        state = State.model_validate(session["state"])
        if body.kind == "fix" and state.last_answer_id == str(mid):
            state.pending_failure = body.value == "no"
            state.outcome = "resolved" if body.value == "yes" else "open"
            conn.execute(
                "UPDATE sessions SET state=%s,updated_at=now(),revision=revision+1 WHERE id=%s",
                (Jsonb(state.model_dump()), sid),
            )
        return {"id": str(fid), "duplicate": False, "value": body.value}


@app.post("/api/sessions/{id}/ticket")
def make_ticket(id: UUID, user=Depends(principal)):
    with connection() as conn:
        session = get_session(conn, id, lock=True, user=user)
        return ensure_ticket(conn, id, State.model_validate(session["state"]))


@app.put("/api/sessions/{id}/ticket")
def edit_ticket(id: UUID, body: TicketIn, user=Depends(principal)):
    with connection() as conn:
        session = get_session(conn, id, lock=True, user=user)
        ensure_ticket(conn, id, State.model_validate(session["state"]))
        return conn.execute(
            "UPDATE tickets SET draft_redacted=%s,edited=true,updated_at=now() WHERE session_id=%s AND problem_id=%s RETURNING id,draft_redacted AS draft,edited",
            (redact(body.draft), id, session["state"].get("problem_id")),
        ).fetchone()


@app.get("/api/guides/{id}")
def guide(id: str, version: str | None = None, section: str | None = None, user=Depends(principal)):
    with connection() as conn:
        rows = conn.execute(
            """SELECT a.id,a.title,a.source_url,a.is_synthetic,a.corpus_version,s.heading,s.section_text,s.steps,s.applicability,s.reference_links,s.request_types
          FROM articles a JOIN sections s ON a.id=s.article_id AND a.corpus_version=s.corpus_version
          WHERE a.id=%s AND a.corpus_version=%s AND (%s::text IS NULL OR s.id=%s)
            AND (%s OR (a.allowed_visibility='private synthetic pilot' AND a.is_synthetic))
          ORDER BY s.chunk_index""",
            (id, version or corpus_version(), section, section, settings().app_mode != "pilot"),
        ).fetchall()
        if not rows:
            raise HTTPException(404, "Guide not found")
        return rows


@app.get("/api/admin/stats")
def stats(authorization: str = Header(default=""), user=Depends(principal)):
    token = settings().admin_token
    authorized = (
        user and user["role"] == "admin"
        if settings().app_mode == "pilot"
        else token and secrets.compare_digest(authorization, "Bearer " + token)
    )
    if not authorized:
        raise HTTPException(401, "Team access token required", headers={"WWW-Authenticate": "Bearer"})
    with connection() as conn:
        return dict(
            sessions=conn.execute("SELECT count(*) AS n FROM sessions").fetchone()["n"],
            decisions=conn.execute(
                "SELECT decision->>'action' AS action,count(*) AS n FROM state_snapshots GROUP BY action"
            ).fetchall(),
            outcomes=conn.execute(
                "SELECT state->>'outcome' AS outcome,count(*) AS n FROM sessions GROUP BY outcome"
            ).fetchall(),
            questions=conn.execute(
                "SELECT count(*) AS n FROM state_snapshots WHERE decision->>'action'='ASK'"
            ).fetchone()["n"],
            feedback=conn.execute(
                "SELECT kind,value,count(*) AS n FROM feedback GROUP BY kind,value"
            ).fetchall(),
        )


@app.get("/api/admin/operations")
def operations(user=Depends(principal)):
    if settings().app_mode != "pilot" or not user or user["role"] != "admin":
        raise HTTPException(403, "Pilot administrator required")
    with connection() as conn:
        totals = conn.execute("""SELECT count(*) AS turns,
          count(*) FILTER(WHERE status='uncertain') AS uncertain,
          count(*) FILTER(WHERE error_code IS NOT NULL) AS errors,
          percentile_cont(ARRAY[0.5,0.95,0.99]) WITHIN GROUP(ORDER BY elapsed_ms) AS latency_ms
          FROM pilot_turns WHERE created_at>now()-interval '24 hours'""").fetchone()
        categories = conn.execute(
            "SELECT error_code,count(*) AS n FROM pilot_turns WHERE created_at>now()-interval '24 hours' AND error_code IS NOT NULL GROUP BY error_code"
        ).fetchall()
        usage = conn.execute(
            "SELECT calls,authorized_limit,budget_usd,reserved_usd,reported_cost_usd FROM provider_usage WHERE id=1"
        ).fetchone()
        cleanup = conn.execute(
            "SELECT max(created_at) AS last_completed,COALESCE(max(created_at)<now()-interval '25 hours',true) AS overdue FROM pilot_audit WHERE event='retention_completed'"
        ).fetchone()
        stages = conn.execute("""SELECT stage.key AS stage,count(*) AS samples,
            percentile_cont(ARRAY[0.5,0.95,0.99]) WITHIN GROUP(ORDER BY stage.value::numeric) AS latency_ms
            FROM pilot_turns p CROSS JOIN LATERAL jsonb_each_text(p.usage->'timings_ms') stage
            WHERE p.created_at>now()-interval '24 hours'
            GROUP BY stage.key ORDER BY stage.key""").fetchall()
        return dict(
            window="24h",
            turns=totals,
            errors=categories,
            usage=usage,
            retention=cleanup,
            stage_latency=stages,
            inference_enabled=settings().inference_enabled,
            provider_health="observed_errors_and_configuration_only",
            alerts=dict(
                uncertain_turn=totals["uncertain"] > 0,
                error_rate=totals["turns"] >= 10 and totals["errors"] / totals["turns"] > 0.05,
                latency=bool(totals["latency_ms"] and totals["latency_ms"][1] > 8000),
                budget=usage["calls"] >= 0.8 * usage["authorized_limit"],
                retention_overdue=cleanup["overdue"],
            ),
        )


def corpus_sections(conn):
    return conn.execute(
        """SELECT count(*) AS n FROM sections s
      JOIN articles a ON a.id=s.article_id AND a.corpus_version=s.corpus_version
      WHERE s.corpus_version=%s AND (%s OR (a.allowed_visibility='private synthetic pilot'
      AND a.is_synthetic AND s.workflow_version IS NOT NULL))""",
        (corpus_version(), settings().app_mode != "pilot"),
    ).fetchone()["n"]
