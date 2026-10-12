"""Pilot source-driven diagnostics and exact artifact continuation, offline."""

from uuid import uuid4
import pytest
from app.config import settings
from app.db import connection
from app.graph import validate_graph
from app.ingest import ingest
from app.models import Guide, State, Interpretation
from app.retrieval import load_active, retrieve
from app import graph
from test_integration import client as integration_client
from test_pilot import login, create
from test_pilot import pilot as pilot  # Register the shared authentication fixture.

client = integration_client


@pytest.fixture(autouse=True)
def corpus(client, pilot, monkeypatch):
    monkeypatch.setattr(settings(), "corpus_version", "synthetic-2026-10-v4")
    ingest()
    login(client)


def send(client, sid, text):
    r = client.post(f"/api/sessions/{sid}/messages", json=dict(text=text, request_id=str(uuid4())))
    assert r.status_code == 200, r.text
    return r.json()


def test_source_intake_and_full_installation(client):
    sid = create(client)
    a = send(client, sid, "I need to download Autodesk")
    assert a["question_field"] == "system_or_app", a
    a = send(client, sid, "AutoCAD on Windows for a student")
    assert a["sources"][0]["id"] == "autodesk-education", a
    assert a["state"]["active_node"] == "check-1"
    a = send(client, sid, "yes")
    assert a["state"]["active_node"] == "check-2" and a["state"]["outcome"] == "open"
    a = send(client, sid, "Download complete")
    assert a["state"]["active_node"] == "check-3" and a["state"]["outcome"] == "open"
    a = send(client, sid, "Installed and opens")
    assert a["state"]["outcome"] == "resolved" and not a["steps"]


def test_negative_access_and_blocker_resume(client):
    sid = create(client)
    send(client, sid, "Install AutoCAD on Windows with education Autodesk access")
    a = send(client, sid, "no")
    assert a["action"] == "HANDOFF" and a["state"]["failures"] == 0, a
    a = send(client, sid, "I can access the download")
    assert a["state"]["active_node"] == "check-2" and a["action"] == "ANSWER", a


def test_version_pinned_across_promotion_and_explanation(client, monkeypatch):
    sid = create(client)
    first = send(client, sid, "Install AutoCAD on Windows with education Autodesk access")
    monkeypatch.setattr(settings(), "corpus_version", "synthetic-2026-10-v3")
    explained = send(client, sid, "Explain this step")
    assert explained["text"].startswith("This checks whether the chosen product")
    assert explained["steps"] == first["steps"]
    a = send(client, sid, "yes")
    assert a["state"]["active_corpus"] == "synthetic-2026-10-v4" and a["state"]["active_node"] == "check-2", a
    assert a["sources"][0]["corpus_version"] == "synthetic-2026-10-v4"
    href = a["sources"][0]["href"]
    r = client.get(href.replace("/sources/", "/api/guides/"))
    assert r.status_code == 200 and r.json()[0]["corpus_version"] == "synthetic-2026-10-v4"
    assert client.get("/api/guides/autodesk-education?version=synthetic-2026-10-v3").status_code == 404


def test_pin_does_not_fall_back_to_first_section(client):
    sid = create(client)
    a = send(client, sid, "Install AutoCAD on Windows with education Autodesk access")
    state = State.model_validate(a["state"])
    with connection() as conn:
        assert load_active(conn, state).id == state.active_section
        state.active_section = "autodesk-education:missing"
        assert load_active(conn, state) is None
        state.active_section = a["state"]["active_section"]
        state.active_workflow_version = "retired-version"
        assert load_active(conn, state) is None


def test_shared_wifi_branch_and_no_failed_observation(client):
    sid = create(client)
    a = send(client, sid, "My home Wi-Fi keeps disconnecting on my laptop")
    assert a["sources"][0]["id"] == "general-wifi", a
    a = send(client, sid, "Other devices too")
    assert a["sources"][0]["id"] == "wifi-shared" and a["state"]["failures"] == 0, a
    a = send(client, sid, "Service problem indicated")
    assert a["action"] == "HANDOFF" and a["state"]["failures"] == 0, a


def test_unknown_reply_and_explanation_do_not_advance(client):
    sid = create(client)
    first = send(client, sid, "Install AutoCAD on Windows with education Autodesk access")
    for text in ["I haven't tried it", "thanks", "Explain this step"]:
        a = send(client, sid, text)
        assert a["state"]["active_node"] == first["state"]["active_node"]
        assert a["state"]["failures"] == 0


def test_fact_provenance_and_explicit_correction(client):
    sid = create(client)
    a = send(client, sid, "Install AutoCAD on Windows with education Autodesk access")
    fact = a["state"]["facts"]["os"]
    assert fact["message_id"] == a["user_message"]["id"] and fact["status"] == "reported"
    a = send(client, sid, "Actually macOS")
    fact = a["state"]["facts"]["os"]
    assert fact["value"] == "macOS" and fact["previous"]["value"] == "Windows"
    assert fact["message_id"] == a["user_message"]["id"]


def test_prefilter_keeps_known_platform_before_top_five(client):
    state = State(category="wifi_network", details={"os": "Windows", "network": "demo-campus"})
    with connection() as conn:
        for ranking in ("dense", "hybrid"):
            guides = retrieve(conn, "macOS demo-guest credential error", state, ranking=ranking)
            assert guides
            assert all(
                g.category == "wifi_network" and g.applicability.get("os", "any") in ("any", "Windows")
                for g in guides
            )
            assert all(g.applicability.get("network", "any") in ("any", "demo-campus") for g in guides)
            assert all(g.corpus_version == "synthetic-2026-10-v4" for g in guides)


def prototype():
    return Guide(
        id="new:1",
        source_id="new",
        title="New product",
        category="software",
        source_url="demo://new",
        corpus_version="synthetic-new",
        heading="Check",
        section_text="Inspect status",
        steps=["Inspect status", "Try the approved local action"],
        applicability={},
        workflow_version="new-1",
        workflow=[
            dict(
                node_id="observe",
                indexes=[0],
                kind="observation",
                prompt="Is the status ready?",
                explanation="A visible status check.",
                transitions=dict(
                    completed="action",
                    failed="@handoff",
                    blocked="@handoff",
                    unknown="@wait",
                    not_tried="@wait",
                ),
                replies={"yes": "completed", "no": "failed"},
            ),
            dict(
                node_id="action",
                indexes=[1],
                kind="action",
                prompt="Does it work?",
                explanation="Confirm the result.",
                transitions=dict(
                    completed="@verify",
                    failed="@handoff",
                    blocked="@handoff",
                    unknown="@wait",
                    not_tried="@wait",
                ),
                replies={"yes": "resolved", "no": "failed"},
            ),
        ],
    )


def test_new_product_graph_needs_no_engine_branch():
    guide = prototype()
    validate_graph(guide)
    state = State(
        active_guide=guide.source_id,
        active_node="observe",
        active_graph=True,
        active_workflow=[n.model_dump() for n in guide.workflow],
    )
    result = Interpretation(outcome="resolved")
    graph.contextual_reply(state, result, "yes")
    assert result.outcome == "unknown"
    graph.advance(state, result)
    assert state.active_node == "action"
    graph.contextual_reply(state, result, "no")
    graph.advance(state, result)
    assert state.workflow_blocked and state.outcome != "resolved"


@pytest.mark.parametrize(
    "mutation",
    [
        "cycle",
        "dangling",
        "unreachable",
        "unknown",
        "untried",
        "invalid-step",
        "premature",
        "duplicate",
        "bad-branch",
    ],
)
def test_ingestion_rejects_invalid_graph(mutation):
    guide = prototype()
    a = guide.workflow[0]
    if mutation == "cycle":
        guide.workflow[1].transitions["completed"] = "observe"
    if mutation == "dangling":
        a.transitions["completed"] = "missing"
    if mutation == "unreachable":
        a.transitions["completed"] = "@verify"
    if mutation == "unknown":
        a.transitions["unknown"] = "action"
    if mutation == "untried":
        a.transitions["not_tried"] = "action"
    if mutation == "invalid-step":
        a.indexes = [99]
    if mutation == "premature":
        a.replies["yes"] = "resolved"
    if mutation == "duplicate":
        guide.workflow[1].node_id = "observe"
    if mutation == "bad-branch":
        a.branches = [dict(field="secret", equals="x", next="action")]
    with pytest.raises(ValueError):
        validate_graph(guide)


def test_known_scope_skips_redundant_entry_observation(client):
    sid = create(client)
    a = send(client, sid, "Only this laptop cannot use home Wi-Fi; my phone works")
    assert a["sources"][0]["id"] == "general-wifi-alternate", a
    assert a["state"]["failures"] == 0


def test_graph_unknown_waits_are_bounded():
    guide = prototype()
    state = State(
        active_guide=guide.source_id,
        active_node="observe",
        active_graph=True,
        active_workflow=[n.model_dump() for n in guide.workflow],
    )
    for _ in range(3):
        graph.advance(state, Interpretation(intent="unsure"))
    assert state.workflow_blocked and state.active_node == "observe"


def test_interpretation_gets_permitted_names_without_asserting_user_facts(client, monkeypatch):
    from app.llm import ScriptedProvider

    original = ScriptedProvider.interpret
    captured = []

    def inspect(self, text, state):
        captured.extend(state.interpretation_vocabulary)
        assert state.details.network is None
        assert "interpretation_vocabulary" not in state.model_dump()
        return original(self, text, state)

    monkeypatch.setattr(ScriptedProvider, "interpret", inspect)
    send(client, create(client), "wifi")
    assert dict(category="wifi_network", field="network", name="demo-campus") in captured
    assert all(r["field"] in {"network", "printer", "system_or_app", "vendor"} for r in captured)


def test_reported_recovery_during_observation_requires_literal_whole_task_evidence():
    from app.service import merge

    guide = prototype()

    def pending(request_type="troubleshoot"):
        return State(
            request_type=request_type,
            active_guide=guide.source_id,
            active_node="observe",
            active_graph=True,
            active_kind="observation",
            active_workflow=[n.model_dump() for n in guide.workflow],
        )

    text = "It connected and websites load now"
    result = merge(
        pending(),
        Interpretation(
            outcome="resolved", intent="thanks", step_result="completed", resolution_evidence=text
        ),
        text,
    )
    assert result.outcome == "resolved"
    for quote, user, task in [
        ("yes", "yes", "troubleshoot"),
        (text, "I do not know", "troubleshoot"),
        ("The download is complete", "The download is complete", "install"),
    ]:
        result = merge(pending(task), Interpretation(outcome="resolved", resolution_evidence=quote), user)
        assert result.outcome != "resolved"


def test_blocked_intake_handoffs_without_attributing_untried_steps(client, monkeypatch):
    from app.llm import ScriptedProvider

    sid = create(client)
    first = send(client, sid, "I need to download Autodesk AutoCAD on Windows")
    assert first["action"] == "ASK"
    monkeypatch.setattr(
        ScriptedProvider,
        "interpret",
        lambda *_: Interpretation(
            step_result="blocked",
            observation="The required product is unavailable",
            steps_tried=["Invented performed installation"],
        ),
    )
    result = send(client, sid, "The product is not available in my account")
    assert result["rule"] == "step_blocked" and result["ticket"]
    assert result["state"]["steps_tried"] == [] and result["state"]["failures"] == 0
