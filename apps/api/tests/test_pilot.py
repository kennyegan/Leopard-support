"""Pilot authorization boundaries; test identities are seeded, never a runtime bypass."""

from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from app.auth import COOKIE, digest, establish_login
from app.config import Settings, settings
from app.db import connection
from app.dialogue import safe_prose
from test_integration import client as integration_client

client = integration_client


@pytest.fixture(autouse=True)
def pilot(client, monkeypatch):
    cfg = settings()
    with connection() as conn:
        assert conn.execute("SELECT current_database() AS name").fetchone()["name"] == "techspot_test"
        # Quota behavior is tested within each test, not by accumulated runs of
        # unrelated tests sharing a persistent local test database.
        conn.execute("DELETE FROM pilot_rate_windows")
    monkeypatch.setattr(cfg, "app_mode", "pilot")
    monkeypatch.setattr(cfg, "dialogue_mode", "conversational")
    monkeypatch.setattr(cfg, "oidc_issuer", "https://issuer.example")
    monkeypatch.setattr(cfg, "web_origin", "https://testserver")
    monkeypatch.setattr(client, "base_url", httpx.URL("https://testserver"))
    client.cookies.clear()
    client.headers.pop("x-csrf-token", None)
    client.headers["origin"] = cfg.web_origin
    yield
    client.cookies.clear()
    client.headers.pop("x-csrf-token", None)
    client.headers.pop("origin", None)


def login(client, role="tester"):
    email, subject = f"{uuid4()}@example.test", str(uuid4())
    with connection() as conn:
        conn.execute("INSERT INTO pilot_invites(email,role) VALUES(%s,%s)", (email, role))
    token = establish_login(dict(iss=settings().oidc_issuer, sub=subject, email=email, email_verified=True))
    client.cookies.set(COOKIE, token)
    result = client.get("/api/auth/me")
    assert result.status_code == 200
    identity = result.json()
    client.headers["x-csrf-token"] = identity["csrf_token"]
    return token, email, identity


def create(client):
    result = client.post("/api/sessions", json={"mode": "policy"})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def test_anonymous_routes_are_closed(client):
    sid = str(uuid4())
    for method, path, body in [
        ("get", f"/api/sessions/{sid}", None),
        ("get", f"/api/sessions/{sid}/snapshots", None),
        ("post", "/api/sessions", {"mode": "policy"}),
        ("post", f"/api/sessions/{sid}/messages", {"text": "I want a person", "request_id": str(uuid4())}),
        ("put", f"/api/sessions/{sid}/ticket", {"draft": "Synthetic"}),
        ("get", "/api/guides/general-wifi", None),
        ("get", "/api/admin/stats", None),
    ]:
        response = client.request(method, path, **({"json": body} if body else {}))
        assert response.status_code == 401, (method, path)


@pytest.mark.parametrize("role", ["tester", "admin"])
def test_other_identity_cannot_read_mutate_or_vote_on_private_session(client, role):
    login(client)
    sid = create(client)
    reply = client.post(
        f"/api/sessions/{sid}/messages", json={"text": "I want a person", "request_id": str(uuid4())}
    ).json()
    assert reply["action"] == "HANDOFF"
    client.cookies.clear()
    login(client, role)
    for method, path, body in [
        ("get", f"/api/sessions/{sid}", None),
        ("get", f"/api/sessions/{sid}/snapshots", None),
        ("post", f"/api/sessions/{sid}/messages", {"text": "I want a person", "request_id": str(uuid4())}),
        ("post", f"/api/sessions/{sid}/ticket", {}),
        ("put", f"/api/sessions/{sid}/ticket", {"draft": "Synthetic change"}),
        (
            "post",
            "/api/feedback",
            dict(
                session_id=sid,
                message_id=reply["id"],
                snapshot_id=reply["snapshot_id"],
                kind="rating",
                value="yes",
            ),
        ),
    ]:
        response = client.request(method, path, **({"json": body} if body is not None else {}))
        assert response.status_code == 404, (method, path, response.text)


def test_owner_access_csrf_logout_and_revocation(client):
    token, email, _ = login(client)
    sid = create(client)
    assert client.get(f"/api/sessions/{sid}").status_code == 200
    csrf = client.headers.pop("x-csrf-token")
    assert client.post("/api/sessions", json={}).status_code == 403
    client.headers["x-csrf-token"] = csrf
    client.headers["origin"] = "https://evil.example"
    assert client.post("/api/sessions", json={}).status_code == 403
    client.headers["origin"] = settings().web_origin
    assert client.get("/api/admin/stats", headers={"authorization": "Bearer ignored"}).status_code == 401
    assert client.post("/api/sessions", json={"mode": "baseline"}).status_code == 403
    with connection() as conn:
        conn.execute("UPDATE pilot_invites SET active=false WHERE email=%s", (email,))
    assert client.get(f"/api/sessions/{sid}").status_code == 401
    with connection() as conn:
        conn.execute("UPDATE pilot_invites SET active=true WHERE email=%s", (email,))
    assert client.post("/api/auth/logout", follow_redirects=False).status_code == 303
    client.cookies.set(COOKIE, token)
    assert client.get(f"/api/sessions/{sid}").status_code == 401


def test_expired_login_is_rejected(client):
    token, _, _ = login(client)
    with connection() as conn:
        conn.execute(
            "UPDATE pilot_logins SET expires_at=now()-interval '1 second' WHERE token_hash=%s",
            (digest(token),),
        )
    assert client.get("/api/auth/me").status_code == 401


def test_login_requires_verified_invited_identity_and_stable_subject(client):
    _, email, _ = login(client)
    for claims in [
        dict(iss=settings().oidc_issuer, sub="different", email=email, email_verified=True),
        dict(iss=settings().oidc_issuer, sub="other", email="uninvited@example.test", email_verified=True),
        dict(iss=settings().oidc_issuer, sub="other", email=email, email_verified=False),
        dict(iss="https://evil.example", sub="other", email=email, email_verified=True),
    ]:
        with pytest.raises(HTTPException) as error:
            establish_login(claims)
        assert error.value.status_code == 403


def test_pilot_configuration_fails_closed():
    cfg = Settings(_env_file=None, app_mode="pilot")
    with pytest.raises(ValueError):
        cfg.validate_pilot()


def test_pilot_ignores_unsupported_model_prose():
    assert safe_prose("Change the DNS server to 192.0.2.1 and try again.") == ""


def test_chunked_oversize_body_cannot_bypass_length_guard(client):
    login(client)
    response = client.post(
        "/api/sessions",
        content=iter([b" " * 11000, b" " * 11000]),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_shared_rate_window_rejects_over_quota(client, monkeypatch):
    login(client)
    monkeypatch.setattr(settings(), "user_requests_per_minute", 2)
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/auth/me").status_code == 429


def test_deletion_removes_entire_owned_conversation_and_preserves_other_user(client):
    import psycopg

    _, _, identity = login(client)
    sid = create(client)
    reply = client.post(
        f"/api/sessions/{sid}/messages", json={"text": "I want a person", "request_id": str(uuid4())}
    ).json()
    assert reply["ticket"]
    with connection() as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("DELETE FROM state_snapshots WHERE session_id=%s", (sid,))
    original_cookie = client.cookies.get(COOKIE)
    client.cookies.clear()
    login(client)
    other = create(client)
    assert client.delete(f"/api/sessions/{sid}").status_code == 404
    client.cookies.clear()
    client.cookies.set(COOKIE, original_cookie)
    client.headers["x-csrf-token"] = identity["csrf_token"]
    assert client.delete(f"/api/sessions/{sid}").json() == {"deleted": True}
    with connection() as conn:
        for table in ["messages", "state_snapshots", "tickets", "feedback"]:
            assert (
                conn.execute(f"SELECT count(*) AS n FROM {table} WHERE session_id=%s", (sid,)).fetchone()["n"]
                == 0
            )
        assert not conn.execute("SELECT 1 FROM sessions WHERE id=%s", (sid,)).fetchone()
        assert conn.execute("SELECT 1 FROM sessions WHERE id=%s", (other,)).fetchone()
        assert (
            conn.execute("SELECT event FROM pilot_audit WHERE object_id=%s", (sid,)).fetchone()["event"]
            == "conversation_deleted"
        )


def test_retention_purges_derived_content_and_respects_dry_run(client):
    from app.cleanup import cleanup

    login(client)
    sid = create(client)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "I want a person", "request_id": str(uuid4())})
    with connection() as conn:
        conn.execute("UPDATE sessions SET created_at=now()-interval '31 days' WHERE id=%s", (sid,))
    assert cleanup()["eligible_sessions"] >= 1
    assert client.get(f"/api/sessions/{sid}").status_code == 200
    cleanup(False)
    assert client.get(f"/api/sessions/{sid}").status_code == 404


@pytest.mark.parametrize(
    "fault",
    [None, "signature", "nonce", "nonce_disabled", "audience", "issuer", "expired", "unverified", "state"],
)
def test_oidc_code_pkce_signature_and_claim_validation(client, monkeypatch, fault):
    import base64
    import hashlib
    import time
    from urllib.parse import parse_qs, urlsplit
    from authlib.integrations.starlette_client import OAuth
    from joserfc import jwt
    from joserfc.jwk import RSAKey
    import app.auth as auth

    key = RSAKey.generate_key(parameters={"kid": "test-signing"})
    email = f"{uuid4()}@example.test"
    with connection() as conn:
        conn.execute("INSERT INTO pilot_invites(email,role) VALUES(%s,'tester')", (email,))
    authorization = {}
    issuer = settings().oidc_issuer

    def transport(request):
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json=dict(
                    issuer=issuer,
                    authorization_endpoint=issuer + "/authorize",
                    token_endpoint=issuer + "/token",
                    jwks_uri=issuer + "/jwks",
                    id_token_signing_alg_values_supported=["RS256"],
                ),
            )
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [key.as_dict(private=False)]})
        assert request.url.path == "/token"
        form = parse_qs(request.content.decode())
        assert form["redirect_uri"] == ["https://testserver/api/auth/callback"]
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"][0].encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert challenge == authorization["code_challenge"][0]
        claims = dict(
            iss=issuer,
            aud="test-client",
            sub="subject-" + email,
            email=email,
            email_verified=True,
            iat=int(time.time()),
            exp=int(time.time()) + 300,
            nonce=authorization["nonce"][0],
        )
        if fault == "nonce":
            claims["nonce"] = "wrong"
        if fault == "nonce_disabled":
            claims.pop("nonce")
            claims["nonce_supported"] = False
        if fault == "audience":
            claims["aud"] = "different-client"
        if fault == "issuer":
            claims["iss"] = "https://evil.example"
        if fault == "expired":
            claims["exp"] = int(time.time()) - 120
        if fault == "unverified":
            claims["email_verified"] = False
        signing_key = RSAKey.generate_key(parameters={"kid": "test-signing"}) if fault == "signature" else key
        encoded = jwt.encode({"alg": "RS256", "kid": "test-signing"}, claims, signing_key)
        return httpx.Response(
            200, json={"access_token": "test-only", "token_type": "Bearer", "id_token": encoded}
        )

    oauth = OAuth()
    fake = oauth.register(
        "pilot",
        client_id="test-client",
        client_secret="test-secret",
        server_metadata_url=issuer + "/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email",
            "code_challenge_method": "S256",
            "transport": httpx.MockTransport(transport),
        },
    )
    monkeypatch.setattr(auth, "client", lambda: fake)
    start = client.get("/api/auth/login", follow_redirects=False)
    assert start.status_code == 302, start.text
    authorization.update(parse_qs(urlsplit(start.headers["location"]).query))
    assert authorization["code_challenge_method"] == ["S256"]
    state = "wrong" if fault == "state" else authorization["state"][0]
    result = client.get(
        "/api/auth/callback", params={"code": "test-code", "state": state}, follow_redirects=False
    )
    if fault:
        assert result.status_code in (400, 403), result.text
        assert client.get("/api/auth/me").status_code == 401
    else:
        assert result.status_code == 303, result.text
        cookie = result.headers["set-cookie"]
        assert (
            "__Host-techspot=" in cookie
            and "HttpOnly" in cookie
            and "Secure" in cookie
            and "SameSite=lax" in cookie
        )
        assert client.get("/api/auth/me").status_code == 200
        assert (
            client.get("/api/auth/callback", params={"code": "test-code", "state": state}).status_code == 400
        )


def test_durable_retry_replays_without_model_or_duplicate_messages(client, monkeypatch):
    from app.llm import ScriptedProvider

    login(client)
    sid = create(client)
    original = ScriptedProvider.interpret
    calls = []

    def interpret(self, text, state):
        calls.append(text)
        return original(self, text, state)

    monkeypatch.setattr(ScriptedProvider, "interpret", interpret)
    body = {"text": "Wi-Fi is failing", "request_id": str(uuid4())}
    first = client.post(f"/api/sessions/{sid}/messages", json=body)
    assert first.status_code == 200
    second = client.post(f"/api/sessions/{sid}/messages", json=body)
    assert second.json() == first.json() and len(calls) == 1
    assert len(client.get(f"/api/sessions/{sid}").json()["messages"]) == 2
    assert client.post(f"/api/sessions/{sid}/messages", json={**body, "text": "different"}).status_code == 409


def test_operator_stage_telemetry_and_retention_alert_exclude_conversation_text(client, monkeypatch):
    from app.llm import ScriptedProvider, ProviderError
    from app.cleanup import cleanup

    login(client, role="admin")
    sid = create(client)
    sensitive_marker = "Synthetic telemetry-private-message"

    def unavailable(*_):
        raise ProviderError("synthetic transport failure", "provider_timeout")

    monkeypatch.setattr(ScriptedProvider, "interpret", unavailable)
    response = client.post(
        f"/api/sessions/{sid}/messages", json=dict(text=sensitive_marker, request_id=str(uuid4()))
    )
    assert response.status_code == 200 and response.json()["response_kind"] == "service_error"
    with connection() as conn:
        record = conn.execute(
            "SELECT usage,error_code FROM pilot_turns WHERE session_id=%s", (sid,)
        ).fetchone()
        assert record["error_code"] == "provider_timeout"
        assert set(record["usage"]["timings_ms"]) == {
            "reservation",
            "preparation",
            "interpretation",
            "decision_before_commit",
        }
        assert all(isinstance(v, int) and v >= 0 for v in record["usage"]["timings_ms"].values())
        conn.execute(
            "UPDATE pilot_audit SET created_at=now()-interval '26 hours' WHERE event='retention_completed'"
        )
    stats = client.get("/api/admin/operations")
    assert stats.status_code == 200 and sensitive_marker not in stats.text
    assert stats.json()["alerts"]["retention_overdue"]
    assert {r["stage"] for r in stats.json()["stage_latency"]} == set(record["usage"]["timings_ms"])
    cleanup(False)
    assert not client.get("/api/admin/operations").json()["alerts"]["retention_overdue"]
    login(client, role="tester")
    assert client.get("/api/admin/operations").status_code == 403


def test_model_call_holds_no_session_lock_and_overlapping_turn_is_rejected(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.llm import ScriptedProvider
    from app.models import Interpretation

    login(client)
    sid = create(client)
    entered, release = Event(), Event()

    def interpret(*args):
        entered.set()
        assert release.wait(5)
        return Interpretation(category="wifi_network")

    monkeypatch.setattr(ScriptedProvider, "interpret", interpret)
    body = {"text": "Wi-Fi is failing", "request_id": str(uuid4())}
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(client.post, f"/api/sessions/{sid}/messages", json=body)
        try:
            assert entered.wait(5)
            with connection() as conn:
                assert conn.execute(
                    "SELECT id FROM sessions WHERE id=%s FOR UPDATE NOWAIT", (sid,)
                ).fetchone()
            assert client.post(f"/api/sessions/{sid}/messages", json=body).status_code == 409
            assert (
                client.post(
                    f"/api/sessions/{sid}/messages", json={**body, "request_id": str(uuid4())}
                ).status_code
                == 409
            )
            assert client.put(f"/api/sessions/{sid}/ticket", json={"draft": "Synthetic"}).status_code == 409
        finally:
            release.set()
        assert future.result(timeout=10).status_code == 200


def test_crashed_turn_is_not_automatically_sent_again(client, monkeypatch):
    from app.llm import ScriptedProvider

    login(client)
    sid = create(client)
    calls = []

    def crash(*args):
        calls.append(True)
        raise RuntimeError("synthetic process failure")

    monkeypatch.setattr(ScriptedProvider, "interpret", crash)
    body = {"text": "Wi-Fi is failing", "request_id": str(uuid4())}
    with pytest.raises(RuntimeError, match="synthetic process failure"):
        client.post(f"/api/sessions/{sid}/messages", json=body)
    result = client.post(f"/api/sessions/{sid}/messages", json=body)
    assert result.status_code == 409 and "cannot be replayed automatically" in result.json()["detail"]
    assert len(calls) == 1
    with connection() as conn:
        assert (
            conn.execute("SELECT status FROM pilot_turns WHERE session_id=%s", (sid,)).fetchone()["status"]
            == "uncertain"
        )
    assert client.get(f"/api/sessions/{sid}").json()["messages"] == []


def test_expired_turn_lease_remains_uncertain_after_retry(client):
    import hashlib

    login(client)
    sid = create(client)
    request_id = str(uuid4())
    with connection() as conn:
        conn.execute(
            """INSERT INTO pilot_turns(id,session_id,request_id,input_hash,state_revision,status,requires_inference,lease_expires_at)
           VALUES(%s,%s,%s,%s,0,'processing',true,now()-interval '1 second')""",
            (uuid4(), sid, request_id, hashlib.sha256(b"Wi-Fi is failing").hexdigest()),
        )
    assert (
        client.post(
            f"/api/sessions/{sid}/messages", json={"text": "Wi-Fi is failing", "request_id": request_id}
        ).status_code
        == 409
    )
    with connection() as conn:
        assert (
            conn.execute("SELECT status FROM pilot_turns WHERE session_id=%s", (sid,)).fetchone()["status"]
            == "uncertain"
        )


def test_revocation_during_model_call_prevents_result_commit(client, monkeypatch):
    from app.llm import ScriptedProvider
    from app.models import Interpretation

    _, email, _ = login(client)
    sid = create(client)

    def revoke(*args):
        with connection() as conn:
            conn.execute("UPDATE pilot_invites SET active=false WHERE email=%s", (email,))
        return Interpretation(category="wifi_network")

    monkeypatch.setattr(ScriptedProvider, "interpret", revoke)
    assert (
        client.post(
            f"/api/sessions/{sid}/messages", json={"text": "Wi-Fi is failing", "request_id": str(uuid4())}
        ).status_code
        == 401
    )
    with connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM messages WHERE session_id=%s", (sid,)).fetchone()["n"]
            == 0
        )


def test_inference_kill_switch_still_allows_human_handoff(client, monkeypatch):
    login(client)
    sid = create(client)
    monkeypatch.setattr(settings(), "inference_enabled", False)
    assert (
        client.post(
            f"/api/sessions/{sid}/messages", json={"text": "Wi-Fi is failing", "request_id": str(uuid4())}
        ).status_code
        == 503
    )
    reply = client.post(
        f"/api/sessions/{sid}/messages", json={"text": "I want a person", "request_id": str(uuid4())}
    )
    assert reply.status_code == 200 and reply.json()["action"] == "HANDOFF"


@pytest.mark.parametrize(
    "text",
    ["My laptop battery is swollen and hot", "Tell me how to bypass admin permission to install software"],
)
def test_obvious_stop_conditions_do_not_require_inference(client, monkeypatch, text):
    from app.llm import ScriptedProvider

    def forbidden(*args, **kwargs):
        raise AssertionError("Stop condition must not call the provider")

    monkeypatch.setattr(ScriptedProvider, "interpret", forbidden)
    login(client)
    sid = create(client)
    r = client.post(f"/api/sessions/{sid}/messages", json=dict(text=text, request_id=str(uuid4())))
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "HANDOFF" and r.json()["rule"] == "unsupported_scope"
    assert not r.json()["steps"]


def test_restore_replays_deletions_and_revokes_restored_logins(client, tmp_path):
    from datetime import datetime, timezone
    from psycopg.types.json import Jsonb
    from app.retention_ledger import export, reconcile

    _, email, _ = login(client)
    sid = create(client)
    client.post(f"/api/sessions/{sid}/messages", json=dict(text="I want a person", request_id=str(uuid4())))
    with connection() as conn:
        backup = conn.execute("SELECT * FROM sessions WHERE id=%s", (sid,)).fetchone()
    created = datetime.now(timezone.utc).isoformat()
    assert client.delete(f"/api/sessions/{sid}").status_code == 200
    with connection() as conn:
        conn.execute("UPDATE pilot_invites SET active=false WHERE email=%s", (email,))
        before_usage = conn.execute("SELECT * FROM provider_usage WHERE id=1").fetchone()
    ledger = tmp_path / "deletions.json"
    export(ledger)
    # A restored older backup contains a conversation the user already deleted.
    with connection() as conn:
        conn.execute("UPDATE pilot_invites SET active=true WHERE email=%s", (email,))
        conn.execute("UPDATE provider_usage SET calls=calls+1 WHERE id=1")
        conn.execute(
            "INSERT INTO sessions(id,owner_id,mode,state) VALUES(%s,%s,%s,%s)",
            (sid, backup["owner_id"], backup["mode"], Jsonb(backup["state"])),
        )
    result = reconcile(ledger, created)
    assert result["replayed_deletions"] >= 1 and result["logins_revoked"]
    assert result["usage_reconciled"] and result["invitations_reconciled"]
    with connection() as conn:
        assert not conn.execute("SELECT 1 FROM sessions WHERE id=%s", (sid,)).fetchone()
        assert conn.execute("SELECT count(*) AS n FROM pilot_logins").fetchone()["n"] == 0
        assert not conn.execute("SELECT active FROM pilot_invites WHERE email=%s", (email,)).fetchone()[
            "active"
        ]
        assert (
            conn.execute("SELECT calls FROM provider_usage WHERE id=1").fetchone()["calls"]
            == before_usage["calls"] + 1
        )
    with pytest.raises(ValueError):
        reconcile(ledger, "2999-01-01T00:00:00+00:00")
