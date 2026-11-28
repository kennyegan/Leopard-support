import json
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from app.config import ROOT, settings
from app.db import connection
from app.ingest import ingest
from app.knowledge import withdraw
from app.models import State
from app.retrieval import load_guide, retrieve
from test_pilot import client as pilot_client, pilot as pilot_configuration, login

client = pilot_client
pilot = pilot_configuration


@pytest.fixture
def campus_flow(client, pilot, monkeypatch, tmp_path):
    monkeypatch.setattr(settings(), "agent_mode", "grounded")
    corpus = json.loads((ROOT / "fixtures/synthetic_guides/campus_flow.json").read_text())
    corpus["version"] = "access-test-" + uuid4().hex
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(corpus))
    monkeypatch.setattr(settings(), "corpus_version", corpus["version"])
    ingest(path)
    return corpus["version"]


def test_retrieval_viewer_and_pinned_load_all_enforce_audience(client, campus_flow):
    _, email, _ = login(client, "admin")
    assert client.get("/api/guides/wifi-staff").status_code == 404
    with connection() as conn:
        assert load_guide(conn, "wifi-staff") is None
        student = retrieve(conn, "staff Wi-Fi support incident process", State())
        assert "wifi-staff" not in {g.source_id for g in student}
        conn.execute(
            "UPDATE pilot_invites SET knowledge_audiences=%s WHERE email=%s",
            (Jsonb(["campus", "staff"]), email),
        )
    response = client.get("/api/guides/wifi-staff")
    assert response.status_code == 200
    assert "embedding" not in response.json()[0]
    with connection() as conn:
        staff = retrieve(
            conn, "staff Wi-Fi support incident process", State(knowledge_audiences=["campus", "staff"])
        )
        assert "wifi-staff" in {g.source_id for g in staff}


def test_withdrawal_blocks_retrieval_old_pins_and_direct_source_urls(client, campus_flow):
    login(client)
    assert client.get("/api/guides/wifi-access").status_code == 200
    with connection() as conn:
        assert withdraw(conn, campus_flow, "wifi-access") == 1
    assert (
        client.get(f"/api/guides/wifi-access?version={campus_flow}&section=wifi-access:0").status_code == 404
    )
    with connection() as conn:
        assert load_guide(conn, "wifi-access", version=campus_flow) is None
        assert "wifi-access" not in {g.source_id for g in retrieve(conn, "Wi-Fi access", State())}
        assert withdraw(conn, campus_flow) == 1
        assert retrieve(conn, "Wi-Fi on Windows", State()) == []


def test_demo_cannot_read_private_corpus_even_with_exact_ids(client, campus_flow, monkeypatch):
    monkeypatch.setattr(settings(), "app_mode", "demo")
    assert client.get("/api/guides/wifi-access").status_code == 404
    with connection() as conn:
        assert load_guide(conn, "wifi-access") is None
        assert retrieve(conn, "Wi-Fi access", State()) == []


def test_review_expiry_hides_content(client, campus_flow):
    login(client)
    with connection() as conn:
        conn.execute("UPDATE articles SET review_due=CURRENT_DATE-1 WHERE corpus_version=%s", (campus_flow,))
    assert client.get("/api/guides/wifi-access").status_code == 404
    with connection() as conn:
        assert retrieve(conn, "Wi-Fi access", State()) == []


def test_reviewed_campus_import_round_trips_and_stays_private(client, pilot, monkeypatch, tmp_path):
    from test_source_import import campus_corpus

    corpus = campus_corpus()  # Reserved example.test host; no real campus material.
    corpus["version"] += "-" + uuid4().hex
    for key, value in dict(
        agent_mode="grounded",
        corpus_version=corpus["version"],
        approved_campus_corpus_version=corpus["version"],
        campus_source_hosts=["kb.example.test"],
    ).items():
        monkeypatch.setattr(settings(), key, value)
    path = tmp_path / "approved-test.json"
    path.write_text(json.dumps(corpus))
    assert ingest(path)["unchanged"] is False
    assert ingest(path)["unchanged"] is True
    login(client)
    source = client.get("/api/guides/wifi-access").json()[0]
    assert not source["is_synthetic"] and source["steps"] == []
    assert source["content_owner"] == "Test support team"
    assert client.get("/api/health").json()["synthetic"] is False
    with connection() as conn:
        matches = retrieve(conn, "Wi-Fi access policy", State(category="email", request_type="access"))
        assert len(matches) == 1 and matches[0].source_id == "wifi-access"
    monkeypatch.setattr(settings(), "app_mode", "demo")
    assert client.get("/api/guides/wifi-access").status_code == 404


def test_recovery_preserves_content_withdrawals_and_reduced_audiences(client, campus_flow, tmp_path):
    from datetime import datetime, timezone
    from app.retention_ledger import export, reconcile

    _, email, _ = login(client)
    backup_at = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        withdraw(conn, campus_flow, "wifi-access")
        conn.execute(
            'UPDATE pilot_invites SET knowledge_audiences=\'["campus","student"]\' WHERE email=%s', (email,)
        )
    ledger = tmp_path / "recovery.json"
    export(ledger)
    with connection() as conn:
        conn.execute("UPDATE articles SET withdrawn_at=NULL WHERE corpus_version=%s", (campus_flow,))
        conn.execute(
            'UPDATE pilot_invites SET knowledge_audiences=\'["campus","staff"]\' WHERE email=%s', (email,)
        )
    reconcile(ledger, backup_at)
    with connection() as conn:
        assert load_guide(conn, "wifi-access") is None
        assert conn.execute(
            "SELECT knowledge_audiences FROM pilot_invites WHERE email=%s", (email,)
        ).fetchone()["knowledge_audiences"] == ["campus", "student"]
