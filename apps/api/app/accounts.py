"""Optional demo accounts: Firebase Authentication ID tokens identify returning users.

Guests keep working without an account. A signed-in user owns the conversations they start or
claim, and can list and delete them. Only the provider subject is stored.
"""

import time
from threading import Lock
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from .config import settings
from .db import connection

HEADER = "x-account-token"
JWKS_URL = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
_keys: dict = {"set": None, "fetched": 0.0}
_lock = Lock()


def _key_set(refresh=False):
    with _lock:
        if refresh or _keys["set"] is None or time.time() - _keys["fetched"] > 3600:
            response = httpx.get(JWKS_URL, timeout=5)
            response.raise_for_status()
            _keys["set"] = KeySet.import_key_set(response.json())
            _keys["fetched"] = time.time()
        return _keys["set"]


def issuer():
    return f"https://securetoken.google.com/{settings().firebase_project_id}"


def verify(token):
    project = settings().firebase_project_id
    rules = jwt.JWTClaimsRegistry(
        leeway=30,
        iss={"essential": True, "value": issuer()},
        aud={"essential": True, "value": project},
        sub={"essential": True},
        exp={"essential": True},
        iat={"essential": True},
    )
    try:
        try:
            decoded = jwt.decode(token, _key_set(), algorithms=["RS256"])
        except (ValueError, JoseError):
            # Google rotates signing keys; retry once with a fresh set before rejecting.
            decoded = jwt.decode(token, _key_set(refresh=True), algorithms=["RS256"])
        rules.validate(decoded.claims)
    except (ValueError, JoseError, httpx.HTTPError):
        raise HTTPException(401, "Your sign-in has expired. Sign in again.") from None
    subject = decoded.claims["sub"]
    if not isinstance(subject, str) or not 0 < len(subject) <= 128:
        raise HTTPException(401, "Your sign-in has expired. Sign in again.")
    return decoded.claims


def current_account(request: Request):
    token = request.headers.get(HEADER, "")
    if not token:
        return None
    if not settings().firebase_project_id or len(token) > 4096:
        raise HTTPException(401, "Accounts are not available on this server.")
    claims = verify(token)
    with connection() as conn:
        row = conn.execute(
            """INSERT INTO accounts(id,issuer,subject) VALUES(%s,%s,%s)
            ON CONFLICT(issuer,subject) DO UPDATE SET last_seen_at=now() RETURNING id""",
            (uuid4(), issuer(), claims["sub"]),
        ).fetchone()
    return {"id": row["id"], "kind": "account", "role": None}
