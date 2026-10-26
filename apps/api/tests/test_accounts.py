"""Optional demo accounts: signed ID tokens, ownership, history, claiming and deletion."""

import time

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from app import accounts
from app.config import settings
from test_integration import client as integration_client, message, session

client = integration_client
PROJECT = "leopard-test"
KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
OTHER_KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})


def token(subject, key=KEY, **overrides):
    now = int(time.time())
    claims = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "sub": subject,
        "iat": now,
        "exp": now + 3600,
        "auth_time": now,
        **overrides,
    }
    return jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)


def signed(subject):
    return {accounts.HEADER: token(subject)}


@pytest.fixture(autouse=True)
def firebase(monkeypatch):
    monkeypatch.setattr(settings(), "firebase_project_id", PROJECT)
    keys = KeySet([RSAKey.import_key(KEY.as_dict(private=False))])
    monkeypatch.setattr(accounts, "_key_set", lambda refresh=False: keys)


def test_guest_chat_still_works_without_an_account(client):
    s = session(client)
    assert message(client, s, "Wi-Fi isn't working.")["action"] == "ASK"
    assert client.get("/api/account/sessions").status_code == 401
    assert client.get("/api/auth/me").json() == {"mode": "demo", "authenticated": False, "accounts": True}


def test_signed_in_conversations_are_private_and_listed(client):
    alice, bob = signed("alice-uid"), signed("bob-uid")
    s = client.post("/api/sessions", json={"mode": "policy"}, headers=alice).json()["id"]
    r = client.post(f"/api/sessions/{s}/messages", json={"text": "Wi-Fi isn't working."}, headers=alice)
    assert r.status_code == 200
    listed = client.get("/api/account/sessions", headers=alice).json()
    assert [row["id"] for row in listed][0] == s
    assert listed[0]["title"] == "Wi-Fi isn't working."
    assert client.get(f"/api/sessions/{s}", headers=alice).status_code == 200
    # Neither a guest nor another account can read or write an owned conversation.
    assert client.get(f"/api/sessions/{s}").status_code == 404
    assert client.get(f"/api/sessions/{s}", headers=bob).status_code == 404
    assert client.post(f"/api/sessions/{s}/messages", json={"text": "hi"}, headers=bob).status_code == 404
    assert s not in [row["id"] for row in client.get("/api/account/sessions", headers=bob).json()]


def test_signing_in_claims_the_current_guest_conversation(client):
    s = session(client)
    message(client, s, "My Demo-Lab printer queue on Windows is stuck.")
    assert client.post(f"/api/sessions/{s}/claim", headers=signed("carol-uid")).json()["claimed"]
    assert s in [row["id"] for row in client.get("/api/account/sessions", headers=signed("carol-uid")).json()]
    assert client.get(f"/api/sessions/{s}").status_code == 404
    # Someone else cannot take it over afterwards.
    assert client.post(f"/api/sessions/{s}/claim", headers=signed("dave-uid")).status_code == 404


def test_owner_can_delete_a_conversation(client):
    erin = signed("erin-uid")
    s = client.post("/api/sessions", json={"mode": "policy"}, headers=erin).json()["id"]
    client.post(f"/api/sessions/{s}/messages", json={"text": "Wi-Fi isn't working."}, headers=erin)
    assert client.delete(f"/api/sessions/{s}", headers=signed("frank-uid")).status_code == 404
    assert client.delete(f"/api/sessions/{s}").status_code == 403
    assert client.delete(f"/api/sessions/{s}", headers=erin).json() == {"deleted": True}
    assert client.get(f"/api/sessions/{s}", headers=erin).status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        token("x", key=OTHER_KEY),
        token("x", aud="someone-else"),
        token("x", iss="https://securetoken.google.com/someone-else"),
        token("x", exp=int(time.time()) - 600),
        token(""),
        "not-a-token",
    ],
)
def test_invalid_tokens_are_rejected(client, bad):
    r = client.get("/api/account/sessions", headers={accounts.HEADER: bad})
    assert r.status_code == 401


def test_accounts_disabled_without_project(client, monkeypatch):
    monkeypatch.setattr(settings(), "firebase_project_id", "")
    assert client.get("/api/account/sessions", headers=signed("alice-uid")).status_code == 401
    assert client.get("/api/auth/me").json()["accounts"] is False
