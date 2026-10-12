"""LOCAL QUALIFICATION ONLY. Selectable synthetic identities; never deploy this issuer."""

import base64
import hashlib
import html
import os
import secrets
import time
from urllib.parse import parse_qs, urlencode
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from joserfc import jwt
from joserfc.jwk import RSAKey

app = FastAPI(docs_url=None, redoc_url=None)
ISSUER = "https://issuer:9443"
REDIRECT = "https://localhost:3443/api/auth/callback"
key = RSAKey.generate_key(parameters={"kid": "local-qualification"})
codes = {}


@app.get("/.well-known/openid-configuration")
def discovery():
    return dict(
        issuer=ISSUER,
        authorization_endpoint=ISSUER + "/authorize",
        token_endpoint=ISSUER + "/token",
        jwks_uri=ISSUER + "/jwks",
        response_types_supported=["code"],
        subject_types_supported=["public"],
        id_token_signing_alg_values_supported=["RS256"],
        code_challenge_methods_supported=["S256"],
    )


@app.get("/jwks")
def jwks():
    return {"keys": [key.as_dict(private=False)]}


@app.get("/authorize")
def authorize(request: Request):
    args = dict(request.query_params)
    if (
        args.get("client_id") != "local-qualification"
        or args.get("redirect_uri") != REDIRECT
        or args.get("code_challenge_method") != "S256"
        or not args.get("nonce")
    ):
        raise HTTPException(400, "Invalid qualification authorization")
    inputs = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in args.items()
    )
    return HTMLResponse(
        '<h1>Local test identity provider</h1><p>Synthetic identities only. This is not production authentication.</p><form action="/approve">'
        + inputs
        + '<label>Test identity <select name="identity"><option value="alice">Alice</option><option value="bob">Bob</option><option value="admin">Admin</option><option value="uninvited">Uninvited</option></select></label><button>Continue with test identity</button></form>'
    )


@app.get("/approve")
def approve(request: Request):
    args = dict(request.query_params)
    if (
        args.get("redirect_uri") != REDIRECT
        or args.get("client_id") != "local-qualification"
        or args.get("identity") not in {"alice", "bob", "admin", "uninvited"}
    ):
        raise HTTPException(400)
    code = secrets.token_urlsafe(32)
    codes[code] = (time.time() + 60, args)
    return RedirectResponse(REDIRECT + "?" + urlencode(dict(code=code, state=args["state"])))


@app.post("/token")
async def token(request: Request):
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    credentials = base64.b64encode(
        ("local-qualification:" + os.environ["OIDC_CLIENT_SECRET"]).encode()
    ).decode()
    if not secrets.compare_digest(request.headers.get("authorization", ""), "Basic " + credentials):
        raise HTTPException(401)
    expiry, args = codes.pop(form.get("code", ""), (0, {}))
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    if (
        expiry < time.time()
        or form.get("redirect_uri") != REDIRECT
        or challenge != args.get("code_challenge")
    ):
        raise HTTPException(400)
    now = int(time.time())
    claims = dict(
        iss=ISSUER,
        aud="local-qualification",
        sub=args["identity"],
        email=args["identity"] + "@example.test",
        email_verified=True,
        iat=now,
        exp=now + 300,
        nonce=args["nonce"],
    )
    return dict(
        access_token="qualification-only",
        token_type="Bearer",
        id_token=jwt.encode({"alg": "RS256", "kid": "local-qualification"}, claims, key),
    )
