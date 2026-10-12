"""Task usefulness and progress against real retrieval; external calls forbidden."""

import pytest
from app.config import settings
from app.ingest import ingest
from app.db import connection
from app.llm import ScriptedProvider
from app.models import Interpretation
from test_integration import client as integration_client, session, message

client = integration_client


@pytest.fixture(autouse=True)
def diagnostic(client, monkeypatch):
    monkeypatch.setattr(settings(), "dialogue_mode", "conversational")
    monkeypatch.setattr(settings(), "corpus_version", "synthetic-2026-10-v3")
    ingest()


def test_exact_user_exchange_never_requests_error_or_returns_crash_guide(client):
    sid = session(client)
    turns = [message(client, sid, t) for t in ["i need to download auto desk", "Laptop", "I'm not sure"]]
    assert turns[0]["question_field"] == "system_or_app"
    for a in turns:
        assert a["state"]["request_type"] == "install"
        assert a["question_field"] not in ("error_text", "symptom", "device")
        assert not any(s["id"].startswith("general-app") for s in a["sources"])
        assert not any("crash" in s or "freeze" in s for s in a["steps"])
    assert any(a["references"] for a in turns)
    assert turns[-1]["steps"] == []  # uncertainty does not replay the catalog instructions


def test_autodesk_end_to_end_progress_and_resolution(client):
    sid = session(client)
    message(client, sid, "I need to download Autodesk")
    route = message(client, sid, "AutoCAD on Windows for a student")
    assert route["sources"][0]["id"] == "autodesk-education", route
    assert route["response_kind"] == "check" and route["progress"]["current"] == 1
    assert route["references"][0]["url"].startswith("https://www.autodesk.com/")
    assert route["state"]["outcome"] == "open"
    download = message(client, sid, "I can access the download")
    assert download["progress"]["current"] == 2 and download["state"]["outcome"] == "open"
    install = message(client, sid, "Download complete")
    assert install["progress"]["current"] == 3
    assert "installer" in " ".join(install["steps"])
    assert not set(route["steps"]) & set(install["steps"])
    done = message(client, sid, "Installed and opens")
    assert done["state"]["outcome"] == "resolved" and done["steps"] == []
    assert client.get(f"/api/sessions/{sid}").json()["state"]["outcome"] == "resolved"


def test_unknown_license_does_not_invent_eligibility(client):
    sid = session(client)
    first = message(client, sid, "I need to download AutoCAD on Windows")
    assert first["question_field"] == "license_route", first
    next_ = message(client, sid, "I'm not sure")
    assert next_["action"] == "ANSWER", next_
    assert next_["sources"][0]["id"] == "autodesk-access-unknown"
    assert next_["state"]["details"]["license_route"] is None
    assert "error_text" not in next_["state"]["questions"]


def test_access_blocker_draft_retains_goal_and_progress(client):
    sid = session(client)
    message(client, sid, "I need to download AutoCAD on Windows for a student")
    blocked = message(client, sid, "Access not approved")
    assert blocked["rule"] == "step_blocked" and blocked["state"]["failures"] == 0
    assert "install" in blocked["ticket"]["draft"] and "Access not approved" in blocked["ticket"]["draft"]
    assert "AutoCAD" in blocked["ticket"]["draft"]


def test_untried_thanks_explanation_do_not_advance_or_repeat_instructions(client):
    sid = session(client)
    first = message(client, sid, "I need to download AutoCAD on Windows for a student")
    untried = message(client, sid, "I haven't tried it")
    assert untried["state"]["active_step"] == 0 and not untried["steps"]
    thanks = message(client, sid, "thanks")
    assert thanks["state"]["active_step"] == 0 and thanks["state"]["failures"] == 0
    explain = message(client, sid, "Explain this step")
    assert explain["steps"] == first["steps"]
    assert explain["state"]["last_answer_id"] == first["id"]


@pytest.mark.parametrize(
    "reply,expected", [("Only this device", "general-wifi-alternate"), ("Other devices too", "wifi-shared")]
)
def test_wifi_observation_changes_next_guide_without_counting_failed_fix(client, reply, expected):
    sid = session(client)
    initial = message(client, sid, "My home Wi-Fi keeps disconnecting on my laptop")
    assert initial["sources"][0]["id"] == "general-wifi", initial
    result = message(client, sid, reply)
    assert result["sources"][0]["id"] == expected, result
    assert result["state"]["failures"] == 0
    assert "general-wifi" in result["state"]["completed_guides"]
    assert result["state"]["observations"] == [reply]
    assert not set(initial["steps"]) & set(result["steps"])


def test_unknown_product_installation_does_not_use_unrelated_vendor_or_crash_steps(client):
    result = message(client, session(client), "I need to download QuasarSketch on Windows")
    if result["action"] == "ASK":
        assert result["question_field"] == "system_or_app"
    assert all(
        s["id"] not in ("general-app", "general-app-alternate") and not s["id"].startswith("autodesk")
        for s in result["sources"]
    )


def test_observation_fix_vote_rejected(client):
    sid = session(client)
    a = message(client, sid, "I need to download AutoCAD on Windows for a student")
    assert (
        client.post(
            "/api/feedback",
            json=dict(
                session_id=sid, message_id=a["id"], snapshot_id=a["snapshot_id"], kind="fix", value="yes"
            ),
        ).status_code
        == 422
    )


def test_schema_valid_model_intent_gates_semantic_retrieval(client, monkeypatch):
    monkeypatch.setattr(
        ScriptedProvider,
        "interpret",
        lambda *args: Interpretation(
            category="software",
            request_type="install",
            details={
                "vendor": "Autodesk",
                "system_or_app": "AutoCAD",
                "os": "Windows",
                "license_route": "education",
            },
        ),
    )
    sid = session(client)
    a = message(client, sid, "I need a CAD program for class")
    assert a["sources"][0]["id"] == "autodesk-education"
    with connection() as c:
        snap = c.execute("SELECT retrieval FROM state_snapshots WHERE message_id=%s", (a["id"],)).fetchone()
        assert all("install" in g["request_types"] for g in snap["retrieval"])


def test_intermediate_step_cannot_be_marked_task_resolved(client):
    sid = session(client)
    message(client, sid, "I need to download AutoCAD on Windows for a student")
    a = message(client, sid, "I can access the download")
    assert a["progress"]["current"] < a["progress"]["total"]
    assert (
        client.post(
            "/api/feedback",
            json=dict(
                session_id=sid, message_id=a["id"], snapshot_id=a["snapshot_id"], kind="fix", value="yes"
            ),
        ).status_code
        == 422
    )


def test_failed_corrective_action_counts_once_and_does_not_repeat(client):
    sid = session(client)
    message(client, sid, "My home Wi-Fi keeps disconnecting on my laptop")
    action = message(client, sid, "Only this device")
    assert action["progress"]["kind"] == "action"
    failed = message(client, sid, "No, that did not fix it")
    assert failed["state"]["failures"] == 1
    assert "general-wifi-alternate" in failed["state"]["attempted_guides"]
    assert all(s["id"] != "general-wifi-alternate" for s in failed["sources"])


def test_comparison_phone_does_not_replace_affected_laptop(client):
    sid = session(client)
    message(client, sid, "My home Wi-Fi keeps disconnecting on my laptop")
    result = message(client, sid, "Only this laptop has the problem. My phone works on the same network.")
    assert result["state"]["details"]["device"] == "laptop"
    assert result["sources"][0]["id"] == "general-wifi-alternate"


def test_access_can_resume_after_blocker_clears(client):
    sid = session(client)
    message(client, sid, "I need to download AutoCAD on Windows for a student")
    message(client, sid, "Access not approved")
    result = message(client, sid, "I can access the download")
    assert result["action"] == "ANSWER" and result["progress"]["current"] == 2
    assert result["state"]["outcome"] == "open" and "ticket" not in result


def test_unknown_named_download_never_becomes_crash_troubleshooting(client):
    sid = session(client)
    message(client, sid, "I need to download some software")
    result = message(client, sid, "QuasarSketch")
    assert result["rule"] == "task_not_documented"
    assert "QuasarSketch" in result["ticket"]["draft"] and "install" in result["ticket"]["draft"]
    assert not result["steps"]


def test_health_exposes_exhausted_allowance_without_an_inference(client, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "provider", "openrouter")
    monkeypatch.setattr(cfg, "allow_external_ai", True)
    monkeypatch.setattr(cfg, "approved_external_corpus_version", cfg.corpus_version)
    monkeypatch.setattr(cfg, "openrouter_api_key", "test-only-placeholder")
    monkeypatch.setattr(cfg, "external_call_limit", 0)
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "limited"
    assert r.json()["ai_requests_remaining"] == 0


def test_missing_details_are_not_user_reported_unavailable_details(client, monkeypatch):
    monkeypatch.setattr(
        ScriptedProvider,
        "interpret",
        lambda *args: Interpretation(
            category="software",
            request_type="install",
            details={"vendor": "Autodesk"},
            unavailable_details=["system_or_app", "os", "license_route"],
        ),
    )
    result = message(client, session(client), "i need to download auto desk")
    assert result["question_field"] == "system_or_app"
    assert result["state"]["unavailable_details"] == []
    assert result["steps"] == []


def test_yes_to_access_question_advances_without_claiming_installation_success(client):
    sid = session(client)
    message(client, sid, "I need to download AutoCAD on Windows for a student")
    result = message(client, sid, "Yes")
    assert result["state"]["outcome"] == "open"
    assert result["progress"]["current"] == 2
    assert "Download from" in " ".join(result["steps"])


def test_no_to_access_question_is_a_blocker_not_a_failed_fix(client):
    sid = session(client)
    message(client, sid, "I need to download AutoCAD on Windows for a student")
    result = message(client, sid, "No")
    assert result["rule"] == "step_blocked"
    assert result["state"]["failures"] == 0
    assert "No" in result["ticket"]["draft"]


def test_corrected_access_route_clears_obsolete_blocker(client):
    sid = session(client)
    message(client, sid, "I need to download AutoCAD on Windows for a student")
    message(client, sid, "Access not approved")
    result = message(client, sid, "Actually, I already have access through an existing license")
    assert result["action"] == "ANSWER"
    assert result["sources"][0]["id"] == "autodesk-existing"
    assert result["state"]["workflow_blocked"] is False


def test_request_purpose_change_updates_category_without_carrying_wifi_context(client):
    sid = session(client)
    message(client, sid, "My home Wi-Fi keeps disconnecting on my laptop")
    result = message(client, sid, "I need to download AutoCAD on Windows for a student")
    assert result["state"]["category"] == "software"
    assert result["sources"][0]["id"] == "autodesk-education"
    assert result["state"]["details"]["network"] is None


def test_unrelated_observation_does_not_complete_current_check(client, monkeypatch):
    sid = session(client)
    first = message(client, sid, "I need to download AutoCAD on Windows for a student")
    monkeypatch.setattr(
        ScriptedProvider,
        "interpret",
        lambda *args: Interpretation(observation="My laptop is silver", step_result="unknown"),
    )
    result = message(client, sid, "My laptop is silver")
    assert result["state"]["active_step"] == first["state"]["active_step"]
    assert result["rule"] == "await_result" and result["steps"] == []


def test_explanation_cannot_advance_workflow_even_with_model_result(client, monkeypatch):
    sid = session(client)
    first = message(client, sid, "I need to download AutoCAD on Windows for a student")
    monkeypatch.setattr(
        ScriptedProvider,
        "interpret",
        lambda *args: Interpretation(
            intent="explain", step_result="completed", observation="What does education access mean?"
        ),
    )
    result = message(client, sid, "What does education access mean?")
    assert result["state"]["active_step"] == first["state"]["active_step"]
    assert result["state"]["steps_tried"] == first["state"]["steps_tried"]


def test_yes_during_intake_does_not_resolve_unknown_task(client):
    sid = session(client)
    message(client, sid, "I need to download Autodesk")
    result = message(client, sid, "Yes")
    assert result["state"]["outcome"] != "resolved"
    assert result["state"]["details"]["system_or_app"] is None


def test_yes_to_final_installation_check_still_resolves(client):
    sid = session(client)
    message(client, sid, "I need to download AutoCAD on Windows for a student")
    message(client, sid, "Yes")
    message(client, sid, "Download complete")
    result = message(client, sid, "Yes")
    assert result["state"]["outcome"] == "resolved"
