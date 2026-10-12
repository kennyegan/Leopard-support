"""Durable pilot turns: short transactions, one reserved attempt, explicit uncertainty."""

import hashlib
import logging
import time
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from .auth import authorize_owner
from .boundaries import rate_limit
from .config import settings
from .db import connection
from .llm import ProviderError, explicit_human, explicit_stop, provider
from .models import Interpretation
from .privacy import redact
from .service import prepare_state, turn

log = logging.getLogger("techspot.turns")


def active_identity(conn, user):
    active = conn.execute(
        """SELECT 1 FROM pilot_logins l JOIN pilot_users u ON u.id=l.user_id
        JOIN pilot_invites i ON i.email=u.email WHERE u.id=%s AND l.csrf_token=%s
        AND l.expires_at>now() AND i.active""",
        (user["id"], user["csrf_token"]),
    ).fetchone()
    if not active:
        raise HTTPException(401, "Sign-in expired or revoked")


def pilot_turn(session_id, body, user):
    if not body.request_id:
        raise HTTPException(422, "A request_id is required for reliable delivery")
    text = redact(body.text.strip())
    input_hash = hashlib.sha256(text.encode()).hexdigest()
    requires_inference = not (explicit_human(text) or explicit_stop(text))
    turn_id = uuid4()
    start = time.monotonic()
    with connection() as conn:
        # Serializes only the small reservation; no network/embedding work here.
        conn.execute("SELECT pg_advisory_xact_lock(741320)")
        active_identity(conn, user)
        session = conn.execute("SELECT * FROM sessions WHERE id=%s FOR UPDATE", (session_id,)).fetchone()
        if not session:
            raise HTTPException(404, "Session not found")
        authorize_owner(session, user)
        if session["mode"] != "policy":
            raise HTTPException(403, "Research mode is unavailable in the pilot")
        conn.execute(
            "UPDATE pilot_turns SET status='uncertain',error_code='worker_interrupted' WHERE status='processing' AND lease_expires_at<now()"
        )
        previous = conn.execute(
            "SELECT * FROM pilot_turns WHERE session_id=%s AND request_id=%s", (session_id, body.request_id)
        ).fetchone()
        if previous:
            if previous["input_hash"] != input_hash:
                raise HTTPException(409, "Request identifier already used for another message")
            if previous["status"] == "completed":
                return previous["response"]
            # Commit expiration marking before returning the uncertainty response.
            status = previous["status"]
        else:
            status = None
            if conn.execute(
                "SELECT 1 FROM pilot_turns WHERE session_id=%s AND status='processing'", (session_id,)
            ).fetchone():
                raise HTTPException(409, "A turn is already running; wait for its result")
            if requires_inference:
                if not settings().inference_enabled:
                    raise HTTPException(
                        503, "Assistant inference is temporarily disabled; you can still request a person"
                    )
                running = conn.execute(
                    "SELECT count(*) AS n FROM pilot_turns WHERE status='processing' AND requires_inference"
                ).fetchone()["n"]
                if running >= settings().inference_concurrency:
                    raise HTTPException(429, "Assistant is busy; try later", headers={"Retry-After": "5"})
                rate_limit("turn-user:" + str(user["id"]), settings().user_turns_per_hour, 3600, conn=conn)
                rate_limit("turn-global", settings().global_turns_per_hour, 3600, conn=conn)
            count = conn.execute(
                "SELECT count(*) AS n FROM messages WHERE session_id=%s", (session_id,)
            ).fetchone()["n"]
            if count >= 100:
                raise HTTPException(429, "Session limit reached. Start a new conversation.")
            conn.execute(
                """INSERT INTO pilot_turns(id,session_id,request_id,input_hash,state_revision,status,requires_inference,lease_expires_at)
                VALUES(%s,%s,%s,%s,%s,'processing',%s,now()+interval '90 seconds')""",
                (turn_id, session_id, body.request_id, input_hash, session["revision"], requires_inference),
            )
    if status:
        detail = (
            "The previous turn may have reached the provider and cannot be replayed automatically. Start a new conversation or request help."
            if status in ("uncertain", "failed")
            else "This request is still running; retry later with the same request ID"
        )
        raise HTTPException(409, detail)
    timings = {"reservation": int((time.monotonic() - start) * 1000)}
    interpreter = None
    try:
        stage_start = time.monotonic()
        with connection() as conn:
            state = prepare_state(conn, session)
        timings["preparation"] = int((time.monotonic() - stage_start) * 1000)
        # No database connection or session lock is held across this call.
        result, error = None, None
        interpreter = provider()
        stage_start = time.monotonic()
        try:
            result = (
                Interpretation(requested_human=explicit_human(text), unsupported=explicit_stop(text))
                if not requires_inference
                else interpreter.interpret(text, state)
            )
        except (ProviderError, ValidationError) as exc:
            error = exc
        timings["interpretation"] = int((time.monotonic() - stage_start) * 1000)
        stage_start = time.monotonic()
        with connection() as conn:
            active_identity(conn, user)
            current = conn.execute("SELECT * FROM sessions WHERE id=%s FOR UPDATE", (session_id,)).fetchone()
            if not current or current["revision"] != session["revision"]:
                raise HTTPException(409, "Conversation changed while this turn ran; outcome requires review")
            record = conn.execute(
                "SELECT status,lease_expires_at>now() AS valid FROM pilot_turns WHERE id=%s FOR UPDATE",
                (turn_id,),
            ).fetchone()
            if not record or record["status"] != "processing" or not record["valid"]:
                raise HTTPException(409, "Turn lease expired; outcome requires review")
            response = turn(
                conn, current, text, prepared=state, interpretation=result, interpretation_error=error
            )
            response["turn_id"] = str(turn_id)
            conn.execute("UPDATE messages SET request_id=%s WHERE id=%s", (body.request_id, response["id"]))
            elapsed = int((time.monotonic() - start) * 1000)
            # Includes retrieval/rendering and message writes, excluding this
            # final telemetry UPDATE/commit. Client latency is measured at ingress.
            timings["decision_before_commit"] = int((time.monotonic() - stage_start) * 1000)
            conn.execute(
                """UPDATE pilot_turns SET status='completed',response=%s,error_code=%s,elapsed_ms=%s,
                provider=%s,usage=%s,completed_at=now() WHERE id=%s""",
                (
                    Jsonb(response),
                    getattr(error, "code", "schema_invalid" if error else None),
                    elapsed,
                    response["provider"],
                    Jsonb({**getattr(interpreter, "last_usage", {}), "timings_ms": timings}),
                    turn_id,
                ),
            )
        log.info(
            "turn_complete id=%s elapsed_ms=%s error=%s stages_ms=%s",
            turn_id,
            elapsed,
            getattr(error, "code", "none"),
            timings,
        )
        return response
    except Exception:
        with connection() as conn:
            conn.execute(
                "UPDATE pilot_turns SET status='uncertain',error_code='turn_interrupted',usage=%s WHERE id=%s AND status='processing'",
                (Jsonb({**getattr(interpreter, "last_usage", {}), "timings_ms": timings}), turn_id),
            )
        log.warning("turn_interrupted id=%s", turn_id)
        raise
