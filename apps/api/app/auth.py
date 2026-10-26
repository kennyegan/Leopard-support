"""OIDC identity, opaque server sessions, invitations and object ownership."""

import hashlib
import secrets
import logging
from functools import lru_cache
from uuid import uuid4

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import RedirectResponse

from .config import settings
from .db import connection

COOKIE = "__Host-techspot"
router = APIRouter(prefix="/api/auth")


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


@lru_cache(maxsize=4)
def oidc_client(issuer, client_id, secret):
    oauth = OAuth()
    return oauth.register(
        "pilot",
        client_id=client_id,
        client_secret=secret,
        server_metadata_url=issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email", "code_challenge_method": "S256", "timeout": 8},
    )


def client():
    cfg = settings()
    return oidc_client(cfg.oidc_issuer, cfg.oidc_client_id, cfg.oidc_client_secret)


def establish_login(claims, old_token=""):
    """Called only after the OIDC library validates signature/audience/nonce/expiry."""
    cfg = settings()
    email = claims.get("email", "").lower()
    if (
        claims.get("iss") != cfg.oidc_issuer
        or not claims.get("sub")
        or claims.get("email_verified") is not True
    ):
        raise HTTPException(403, "Verified invited identity required")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with connection() as conn:
        invite = conn.execute(
            "SELECT * FROM lock_pilot_invitation(%s)", (email,)
        ).fetchone()
        if not invite:
            raise HTTPException(403, "This account is not invited to the pilot")
        user = conn.execute("SELECT * FROM pilot_users WHERE email=%s", (email,)).fetchone()
        if user and (user["issuer"], user["subject"]) != (claims["iss"], claims["sub"]):
            raise HTTPException(403, "Identity change requires administrator review")
        if not user:
            user = conn.execute(
                "INSERT INTO pilot_users(id,issuer,subject,email) VALUES(%s,%s,%s,%s) RETURNING *",
                (uuid4(), claims["iss"], claims["sub"], email),
            ).fetchone()
        if old_token:
            conn.execute("DELETE FROM pilot_logins WHERE token_hash=%s", (digest(old_token),))
        conn.execute(
            "INSERT INTO pilot_logins(token_hash,user_id,csrf_token,expires_at) VALUES(%s,%s,%s,now()+(%s * interval '1 hour'))",
            (digest(token), user["id"], csrf, cfg.login_hours),
        )
        conn.execute("INSERT INTO pilot_audit(event,actor_id) VALUES('login',%s)", (user["id"],))
    return token


def authenticate(request):
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 100:
        raise HTTPException(401, "Sign in to the private pilot")
    with connection() as conn:
        user = conn.execute(
            """SELECT u.id,i.role,l.csrf_token FROM pilot_logins l
            JOIN pilot_users u ON u.id=l.user_id JOIN pilot_invites i ON i.email=u.email
            WHERE l.token_hash=%s AND l.expires_at>now() AND i.active""",
            (digest(token),),
        ).fetchone()
    if not user:
        raise HTTPException(401, "Sign in to the private pilot")
    return user


def principal(request: Request):
    if settings().app_mode == "demo":
        from .accounts import current_account

        return current_account(request)
    return getattr(request.state, "principal", None) or authenticate(request)


def authorize_owner(row, user):
    if settings().app_mode == "demo":
        # Guest conversations stay reachable by id; owned ones only by their account.
        if row.get("account_id") and (not user or row["account_id"] != user["id"]):
            raise HTTPException(404, "Session not found")
        return
    if settings().app_mode == "pilot" and (not user or row.get("owner_id") != user["id"]):
        # Admin stats access does not implicitly grant private conversation access.
        raise HTTPException(404, "Session not found")


def csrf_check(request, user):
    if request.headers.get("origin", "") != settings().web_origin.rstrip("/"):
        raise HTTPException(403, "Same-origin request required")
    if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), user["csrf_token"]):
        raise HTTPException(403, "Invalid request token")


@router.get("/login")
async def login(request: Request):
    if settings().app_mode != "pilot":
        raise HTTPException(404, "Pilot sign-in is unavailable")
    request.session.clear()
    try:
        return await client().authorize_redirect(
            request, settings().web_origin.rstrip("/") + "/api/auth/callback"
        )
    except Exception:
        raise HTTPException(503, "Sign-in provider unavailable") from None


@router.get("/callback")
async def callback(request: Request):
    if settings().app_mode != "pilot":
        raise HTTPException(404, "Pilot sign-in is unavailable")
    try:
        token = await client().authorize_access_token(request, leeway=30)
        claims = token.get("userinfo")
        if not token.get("id_token") or not claims or claims.get("nonce_supported") is False:
            raise ValueError("ID token required")
        login_token = establish_login(claims, request.cookies.get(COOKIE, ""))
    except HTTPException:
        raise
    except Exception as error:
        logging.getLogger("techspot.auth").warning("oidc_callback_rejected type=%s", type(error).__name__)
        raise HTTPException(400, "Sign-in could not be verified; start again") from None
    finally:
        request.session.clear()
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE,
        login_token,
        max_age=settings().login_hours * 3600,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/me")
def me(request: Request):
    user = principal(request)
    if settings().app_mode == "demo":
        return {"mode": "demo", "authenticated": user is not None, "accounts": bool(settings().firebase_project_id)}
    return {
        "mode": "pilot",
        "authenticated": True,
        "user_id": str(user["id"]),
        "role": user["role"],
        "csrf_token": user["csrf_token"],
    }


@router.post("/logout")
def logout(request: Request):
    user = principal(request)
    with connection() as conn:
        conn.execute(
            "DELETE FROM pilot_logins WHERE token_hash=%s", (digest(request.cookies.get(COOKIE, "")),)
        )
        if user:
            conn.execute("INSERT INTO pilot_audit(event,actor_id) VALUES('logout',%s)", (user["id"],))
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="lax", path="/")
    return response
