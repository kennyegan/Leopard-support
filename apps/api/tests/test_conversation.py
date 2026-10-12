"""New-mode journeys against real PostgreSQL/pgvector, with offline interpretation."""

from decimal import Decimal
import json
import pytest
from app.config import settings
from app.db import connection
from app.ingest import ingest
from app.llm import OpenRouterProvider, ProviderError, reserve_external_call
from app.models import Interpretation, State
from app.service import merge
from test_integration import client as integration_client, session, message

client = integration_client


@pytest.fixture(autouse=True)
def conversational(client, monkeypatch):
    monkeypatch.setattr(settings(), "dialogue_mode", "conversational")
    monkeypatch.setattr(settings(), "corpus_version", "synthetic-2026-10-v2")
    ingest()


def test_bare_wifi_explanation_context_and_resolution(client):
    sid = session(client)
    first = message(client, sid, "wifi")
    assert first["action"] == "ASK" and first["question_field"] == "symptom"
    explain = message(client, sid, "What do you mean by that?")
    assert explain["response_kind"] == "explanation"
    assert len(explain["state"]["questions"]) == 1
    answer = message(client, sid, "My home Wi-Fi disconnects every few minutes on my laptop")
    assert answer["action"] == "ANSWER", answer
    assert answer["sources"][0]["id"].startswith("general-wifi")
    assert answer["state"]["details"]["os"] is None
    assert answer["state"]["details"]["network"] == "home"
    explanation = message(client, sid, "What does the first step mean?")
    assert explanation["response_kind"] == "explanation"
    assert explanation["state"]["last_answer_id"] == answer["id"]
    assert explanation["state"]["failures"] == 0
    done = message(client, sid, "It works now")
    assert done["response_kind"] == "status" and not done["steps"]
    assert done["state"]["outcome"] == "resolved"
    assert client.get(f"/api/sessions/{sid}").json()["state"]["outcome"] == "resolved"
    assert (
        client.post(
            "/api/feedback",
            json=dict(
                session_id=sid,
                message_id=done["id"],
                snapshot_id=done["snapshot_id"],
                kind="fix",
                value="yes",
            ),
        ).status_code
        == 422
    )


def test_failed_checks_are_distinct_and_ticket_remembers_them(client):
    sid = session(client)
    first = message(client, sid, "My home Wi-Fi disconnects on my laptop")
    second = message(client, sid, "It still disconnects after those checks")
    assert first["action"] == second["action"] == "ANSWER", (first, second)
    assert first["sources"][0]["id"] != second["sources"][0]["id"]
    final = message(client, sid, "No, that did not fix it")
    assert final["rule"] == "repeated_failure" and final["state"]["failures"] == 2
    assert len(final["state"]["attempted_guides"]) == 2
    assert "home" in final["ticket"]["draft"]


def test_unknown_issue_gets_intake_and_unknown_answers_do_not_repeat(client):
    sid = session(client)
    turns = [
        message(client, sid, t)
        for t in [
            "The room reservation widget has a strange glitch",
            "I'm not sure",
            "I'm not sure",
            "I'm not sure",
        ]
    ]
    assert [t["action"] for t in turns] == ["ASK", "ASK", "ASK", "HANDOFF"]
    fields = [t["question_field"] for t in turns[:3]]
    assert len(set(fields)) == 3
    assert turns[-1]["rule"] == "question_cap"


def test_provider_problem_is_not_technical_handoff_and_human_bypasses_it(client, monkeypatch):
    def fail(*args):
        raise ProviderError("test outage")

    monkeypatch.setattr("app.llm.ScriptedProvider.interpret", fail)
    sid = session(client)
    error = message(client, sid, "My app stopped working")
    assert error["response_kind"] == "service_error" and "ticket" not in error
    assert error["state"]["outcome"] == "open"
    human = message(client, sid, "I want a person")
    assert human["rule"] == "explicit_human_request" and "ticket" in human


def test_new_issue_does_not_inherit_edited_ticket(client):
    sid = session(client)
    first = message(client, sid, "I want a person about my printing problem")
    client.put(f"/api/sessions/{sid}/ticket", json={"draft": "Edited printing issue"})
    second = message(client, sid, "New issue: my home Wi-Fi disconnects on my laptop")
    assert second["state"]["problem_id"] != first["state"]["problem_id"]
    assert client.get(f"/api/sessions/{sid}").json()["ticket"] is None
    final = message(client, sid, "I want a person")
    assert "Edited printing issue" not in final["ticket"]["draft"]
    assert "Wi-Fi" in final["ticket"]["draft"] and not final["ticket"]["edited"]
    with connection() as conn:
        prior = conn.execute(
            "SELECT draft_redacted FROM tickets WHERE id=%s", (first["ticket"]["id"],)
        ).fetchone()
        assert prior["draft_redacted"] == "Edited printing issue"


def test_model_gets_history_skill_and_natural_wording(client, monkeypatch):
    captured = []

    def fake_call(self, prompt, schema):
        captured.append(json.loads(prompt))
        return Interpretation(
            category="wifi_network",
            intent="vague_issue",
            acknowledgement="Let's narrow down the connection problem.",
            question_drafts=[
                {"field": "symptom", "text": "Does your connection drop, or can you never connect?"}
            ],
        )

    monkeypatch.setattr("app.llm.OpenRouterProvider.call", fake_call)
    monkeypatch.setattr(settings(), "provider", "openrouter")
    sid = session(client)
    result = message(client, sid, "wifi")
    assert "Does your connection drop" in result["text"]
    message(client, sid, "It drops")
    assert len(captured) == 2  # one interpretation per turn; no wording call
    assert len(captured[1]["recent_dialogue"]) == 2
    assert "troubleshooting" in captured[1]["troubleshooting_skill"].lower()
    assert "recent_dialogue" not in result["state"]


def test_transport_enforces_new_budget_and_schema(client, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "allow_external_ai", True)
    monkeypatch.setattr(cfg, "openrouter_api_key", "test-placeholder")
    monkeypatch.setattr(cfg, "approved_external_corpus_version", cfg.corpus_version)
    monkeypatch.setattr(cfg, "external_call_limit", 30)
    with connection() as conn:
        original = conn.execute("SELECT * FROM provider_usage WHERE id=1").fetchone()
        conn.execute(
            "UPDATE provider_usage SET calls=0,authorized_limit=30,budget_usd=1,reserved_usd=0,reported_cost_usd=0 WHERE id=1"
        )

    def fake_post(url, **kwargs):
        body = kwargs["json"]
        assert body["provider"]["max_price"] == {"prompt": 1, "completion": 5, "request": 0}
        assert body["reasoning"] == {"enabled": False}
        assert body["max_tokens"] == 1600

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "usage": {"cost": 0.001},
                    "choices": [
                        {"finish_reason": "stop", "message": {"content": Interpretation().model_dump_json()}}
                    ],
                }

        return Response()

    monkeypatch.setattr("app.llm.httpx.post", fake_post)
    try:
        OpenRouterProvider().interpret("wifi", State())
        with connection() as conn:
            row = conn.execute("SELECT * FROM provider_usage WHERE id=1").fetchone()
            assert row["calls"] == 1 and row["reserved_usd"] == Decimal("0.033")
            assert row["reported_cost_usd"] == Decimal("0.001")
            conn.execute("UPDATE provider_usage SET calls=30 WHERE id=1")
        with pytest.raises(ProviderError, match="budget exhausted"):
            reserve_external_call(cfg.openrouter_api_key, cfg.openrouter_model, Decimal("0.033"))
    finally:
        with connection() as conn:
            conn.execute(
                "UPDATE provider_usage SET calls=%s,authorized_limit=%s,budget_start_calls=%s,budget_usd=%s,reserved_usd=%s,reported_cost_usd=%s WHERE id=1",
                tuple(
                    original[k]
                    for k in [
                        "calls",
                        "authorized_limit",
                        "budget_start_calls",
                        "budget_usd",
                        "reserved_usd",
                        "reported_cost_usd",
                    ]
                ),
            )


def test_correction_preserves_issue_and_resets_applicability():
    state = State(
        category="wifi_network",
        details={"os": "macOS", "network": "home"},
        last_answer_id="a",
        last_guide="g",
    )
    result = merge(
        state, Interpretation(category="wifi_network", details={"os": "Windows"}), "Actually Windows"
    )
    assert result.details.network == "home" and result.details.os == "Windows"
    assert result.last_guide is None


def test_not_tried_is_not_a_failed_attempt(client):
    sid = session(client)
    message(client, sid, "My home Wi-Fi disconnects on my macOS laptop")
    result = message(
        client, sid, "Actually Windows. It still disconnects, but I haven't tried the checks yet"
    )
    assert result["state"]["failures"] == 0
    assert result["state"]["details"]["os"] == "Windows"
