"""Actual-byte request limits and PostgreSQL-backed shared rate windows."""

import hashlib
import time
from contextlib import nullcontext

from fastapi import HTTPException
from starlette.responses import JSONResponse

from .config import settings
from .db import connection


class BodyLimitMiddleware:
    def __init__(self, app, limit=20000):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            body.extend(event.get("body", b""))
            if len(body) > self.limit:
                response = JSONResponse({"detail": "Request too large"}, status_code=413)
                return await response(scope, receive, send)
            if not event.get("more_body", False):
                break
        delivered = False

        async def limited_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, limited_receive, send)


def rate_limit(key, limit, seconds=60, conn=None):
    now = int(time.time())
    start = now - now % seconds
    # Hash identifiers so rate storage contains neither IPs nor identity strings.
    hashed = hashlib.sha256(key.encode()).hexdigest()
    with nullcontext(conn) if conn is not None else connection() as conn:
        row = conn.execute(
            """INSERT INTO pilot_rate_windows(key,window_start,count,expires_at)
            VALUES(%s,%s,1,to_timestamp(%s)) ON CONFLICT(key,window_start)
            DO UPDATE SET count=pilot_rate_windows.count+1
            WHERE pilot_rate_windows.count<%s RETURNING count""",
            (hashed, start, start + seconds * 2, limit),
        ).fetchone()
    if not row:
        raise HTTPException(
            429, "Request allowance reached; try later", headers={"Retry-After": str(seconds)}
        )


def pilot_access(request):
    from .auth import authenticate, csrf_check

    public = {"/health", "/api/health", "/api/live", "/api/ready", "/api/auth/login", "/api/auth/callback"}
    if request.url.path in public:
        if request.url.path.startswith("/api/auth/"):
            rate_limit("login:" + (request.client.host if request.client else "unknown"), 30)
        return None
    user = authenticate(request)
    rate_limit("request:" + str(user["id"]), settings().user_requests_per_minute)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        csrf_check(request, user)
    return user
