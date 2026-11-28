from uuid import uuid4

import pytest

from app.db import connection
from app.grounding import Citation, GroundedAnswer, Statement
from app.knowledge import withdraw
from app.llm import ScriptedProvider
from app.models import Interpretation
from test_knowledge_access import (
    campus_flow as flow_fixture,
    client as pilot_client,
    pilot as pilot_configuration,
)
from test_pilot import create, login

client = pilot_client
pilot = pilot_configuration
campus_flow = flow_fixture


def send(client, sid, text, request_id=None):
    return client.post(
        f"/api/sessions/{sid}/messages", json={"text": text, "request_id": request_id or str(uuid4())}
    )


def test_source_reader_receives_retrieved_evidence_and_owned_history(client, campus_flow, monkeypatch):
    login(client)
    sid = create(client)
    seen = []
    original = ScriptedProvider.ground

    def inspect(self, text, state, material):
        seen.append(material)
        assert all(m["section_id"] != "wifi-staff:0" for m in material)
        assert any("synthetic training example" in m["text"] for m in material)
        return original(self, text, state, material)

    monkeypatch.setattr(ScriptedProvider, "ground", inspect)
    request_id = str(uuid4())
    result = send(client, sid, "How do students access the demo-campus Wi-Fi practice network?", request_id)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["action"] == "ANSWER" and body["grounding"], body
    assert body["sources"][0]["is_synthetic"] is True
    assert len(seen) == 1
    assert (
        send(client, sid, "How do students access the demo-campus Wi-Fi practice network?", request_id).json()
        == body
    )
    assert len(seen) == 1  # Idempotent replay never calls either model stage again.
    history = client.get("/api/account/sessions")
    assert history.status_code == 200 and str(history.json()[0]["id"]) == sid
    saved = client.get(f"/api/sessions/{sid}").json()
    assert saved["messages"][-1]["response"]["grounding"] == body["grounding"]
    draft = send(client, sid, "I want a person").json()
    assert draft["action"] == "HANDOFF" and "not submitted" in draft["ticket"]["draft"]
    assert client.delete(f"/api/sessions/{sid}").json()["deleted"] is True
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    with connection() as conn:
        for table in ("messages", "state_snapshots", "tickets", "pilot_turns"):
            assert (
                conn.execute(f"SELECT count(*) AS n FROM {table} WHERE session_id=%s", (sid,)).fetchone()["n"]
                == 0
            )


def test_extractor_guess_is_quarantined_before_rag(client, campus_flow, monkeypatch):
    login(client)
    sid = create(client)
    monkeypatch.setattr(
        ScriptedProvider,
        "interpret",
        lambda *args: Interpretation(category="wifi_network", details={"os": "Windows"}),
    )
    body = send(client, sid, "My Wi-Fi will not connect.").json()
    assert body["state"]["details"]["os"] is None
    assert body["state"]["uncertain_facts"]["os"]["status"] == "unverified"
    assert "os" not in body["state"]["facts"]
    assert all(source["id"] != "wifi-win" for source in body["sources"])


def test_reader_can_request_only_a_documented_missing_detail(client, campus_flow, monkeypatch):
    login(client)
    sid = create(client)

    def clarify(self, text, state, material):
        assert "os" in {c["field"] for c in state.grounding_clarifications}
        return GroundedAnswer(status="needs_detail", clarification_field="os")

    monkeypatch.setattr(ScriptedProvider, "ground", clarify)
    body = send(client, sid, "My demo-campus Wi-Fi will not connect.").json()
    assert body["action"] == "ASK" and body["question_field"] == "os"
    assert body["steps"] == [] and body["sources"] == []
    assert body["state"]["questions"] == ["os"]


def test_reader_can_combine_context_without_inventing_procedure_steps(client, campus_flow, monkeypatch):
    login(client)
    sid = create(client)

    def combine(self, text, state, material):
        assert {m["section_id"] for m in material} == {"wifi-win:0", "wifi-access:0"}
        return GroundedAnswer(
            status="answer",
            statements=[
                Statement(
                    text="The documentation describes the fictional network and a Windows connection check.",
                    citations=[Citation(section_id=m["section_id"], quote=m["text"][:300]) for m in material],
                )
            ],
        )

    monkeypatch.setattr(ScriptedProvider, "ground", combine)
    body = send(
        client, sid, "My demo-campus Wi-Fi stopped working on Windows and reports a demo credential error."
    ).json()
    assert body["action"] == "ANSWER" and len(body["sources"]) == 2
    assert body["steps"][0] == "Open the Wi-Fi settings on your Windows device."
    assert body["state"]["active_guide"] == "wifi-win"


@pytest.mark.parametrize("failure", ["unsupported", "fabricated_quote"])
def test_no_unverified_advice_is_displayed(client, campus_flow, monkeypatch, failure):
    login(client)
    sid = create(client)

    def respond(self, text, state, material):
        if failure == "unsupported":
            return GroundedAnswer(status="insufficient")
        return GroundedAnswer(
            status="answer",
            statements=[
                Statement(
                    text="The campus requires a secret access code.",
                    citations=[
                        Citation(
                            section_id=material[0]["section_id"],
                            quote="A fabricated quote not present in any source.",
                        )
                    ],
                )
            ],
        )

    monkeypatch.setattr(ScriptedProvider, "ground", respond)
    body = send(client, sid, "How do students access the demo-campus Wi-Fi practice network?").json()
    assert body["action"] == "HANDOFF" and body["sources"] == [] and body["steps"] == []
    assert "secret access code" not in body["text"]
    assert ("ticket" in body) is (failure == "unsupported")


def test_withdrawal_during_model_call_prevents_commit(client, campus_flow, monkeypatch):
    login(client)
    sid = create(client)
    original = ScriptedProvider.ground

    def withdraw_during_call(self, text, state, material):
        with connection() as conn:
            withdraw(conn, campus_flow)
        return original(self, text, state, material)

    monkeypatch.setattr(ScriptedProvider, "ground", withdraw_during_call)
    result = send(client, sid, "How do students access the demo-campus Wi-Fi practice network?")
    assert result.status_code == 409, result.text
    assert client.get(f"/api/sessions/{sid}").json()["messages"] == []


def test_issue_resume_and_attempts_survive_real_prompt_redaction(client, campus_flow, monkeypatch):
    import json

    from app.llm import StructuredProvider
    from app.privacy import redact

    login(client)
    sid = create(client)
    first = send(
        client, sid, "My demo-campus Wi-Fi stopped working on Windows with a demo credential error."
    ).json()
    original_id = first["state"]["problem_id"]
    assert first["steps"]
    reported = "I reconnected once"
    answers = iter(
        [
            Interpretation(step_result="failed", outcome="failed", steps_tried=[reported, first["steps"][0]]),
            Interpretation(
                new_problem=True,
                category="printing",
                request_type="how_to",
                summary="A separate printer question",
            ),
        ]
    )
    monkeypatch.setattr(ScriptedProvider, "interpret", lambda *_: next(answers))
    failed = send(client, sid, reported + ". It still fails.").json()
    assert failed["state"]["failures"] == 1 and failed["state"]["steps_tried"] == [reported]
    switched = send(client, sid, "Separate question about a printer.").json()
    other_id = switched["state"]["problem_id"]
    assert other_id != original_id

    class Reader(StructuredProvider):
        def call(self, prompt, schema):
            payload = json.loads(redact(prompt))
            (choice,) = payload["suspended_issues"]
            assert choice["category"] == "wifi_network" and choice["problem_id"] == "issue-1"
            assert original_id not in prompt
            return Interpretation(
                intent="resume",
                resume_problem_id=choice["problem_id"],
                resume_evidence="back to the Wi-Fi issue",
            )

    monkeypatch.setattr(
        ScriptedProvider, "interpret", lambda self, text, state: Reader().interpret(text, state)
    )
    resumed = send(client, sid, "Let's go back to the Wi-Fi issue").json()
    assert resumed["state"]["problem_id"] == original_id and resumed["rule"] == "issue_resumed"
    assert reported in resumed["text"] and not resumed["steps"]
    draft = send(client, sid, "I want a person").json()["ticket"]["draft"]
    assert "Category: wifi_network" in draft and "Attempted steps: I reconnected once\n" in draft
    assert first["steps"][0] not in draft


def test_bad_resume_offers_specific_choice_without_switching_or_creating_ticket(
    client, campus_flow, monkeypatch
):
    login(client)
    sid = create(client)
    first = send(client, sid, "My Wi-Fi drops.").json()
    monkeypatch.setattr(
        ScriptedProvider, "interpret", lambda *_: Interpretation(new_problem=True, category="printing")
    )
    second = send(client, sid, "A different printer problem.").json()
    monkeypatch.setattr(
        ScriptedProvider,
        "interpret",
        lambda *_: Interpretation(
            intent="resume", resume_problem_id="issue-9", resume_evidence="return to it"
        ),
    )
    choose = send(client, sid, "Please return to it").json()
    assert choose["action"] == "ASK" and choose["state"]["problem_id"] == second["state"]["problem_id"]
    assert "ticket" not in choose and choose["steps"] == []
    resumed = send(client, sid, choose["options"][0]).json()
    assert resumed["state"]["problem_id"] == first["state"]["problem_id"]


def test_record_questions_use_exact_owned_draft_without_inference(client, campus_flow, monkeypatch):
    login(client)
    sid = create(client)
    monkeypatch.setattr(
        ScriptedProvider, "interpret", lambda *_: pytest.fail("read-only question used the model")
    )
    monkeypatch.setattr("app.service.retrieve", lambda *_: pytest.fail("record lookup used documentation"))
    empty = send(client, sid, "Did you submit anything?").json()
    assert "no saved draft" in empty["text"] and "ticket" not in empty
    assert client.get(f"/api/sessions/{sid}").json()["ticket"] is None
    note = "I connected once, then stopped. Please contact me tomorrow."
    assert client.put(f"/api/sessions/{sid}/ticket", json={"draft": note}).is_success
    for text, expected in (
        ("What did you put in that draft?", note),
        ("Did you submit my ticket?", "has not submitted"),
        ("Did you write that I tried reconnecting?", note),
    ):
        reply = send(client, sid, text).json()
        assert reply["action"] == "ANSWER" and expected in reply["text"]
        assert reply["ticket"]["draft"] == note and reply["sources"] == [] and reply["steps"] == []


def test_vague_intake_and_untried_information_do_not_escalate(client, campus_flow, monkeypatch):
    login(client)
    sid = create(client)
    monkeypatch.setattr(ScriptedProvider, "interpret", lambda *_: Interpretation(intent="vague_issue"))
    first = send(client, sid, "This thing won't connect.").json()
    assert first["action"] == "ASK" and "ticket" not in first
    monkeypatch.setattr(
        ScriptedProvider,
        "interpret",
        lambda *_: Interpretation(category="wifi_network", request_type="how_to"),
    )
    info = send(client, sid, "Which training network is for students?").json()
    assert info["grounding"] and not info["steps"]
    monkeypatch.setattr(ScriptedProvider, "interpret", lambda *_: Interpretation(step_result="not_tried"))
    waiting = send(client, sid, "Okay, I haven't checked yet.").json()
    assert (
        waiting["rule"] == "untried_suggestion"
        and waiting["state"]["failures"] == 0
        and "ticket" not in waiting
    )


def test_mail_evidence_excludes_wifi_procedures_and_clarifications(
    client, campus_flow, monkeypatch, tmp_path
):
    import json
    from app.config import ROOT, settings
    from app.ingest import ingest

    corpus = json.loads((ROOT / "fixtures/synthetic_guides/campus_flow.json").read_text())
    corpus["version"] = campus_flow + "-mail"
    corpus["guides"].append(
        dict(
            id="practice-mail",
            title="Missing notices in the practice mailbox",
            category="email",
            source_url="demo://practice-mail",
            is_synthetic=True,
            applicability={},
            content_kind="information",
            sections=[
                dict(
                    heading="Missing mail",
                    text="Missing notices in the practice mailbox are listed in the message log.",
                    steps=[],
                )
            ],
        )
    )
    document = tmp_path / "mail.json"
    document.write_text(json.dumps(corpus))
    monkeypatch.setattr(settings(), "corpus_version", corpus["version"])
    ingest(document)
    login(client)
    sid = create(client)
    monkeypatch.setattr(ScriptedProvider, "interpret", lambda *_: Interpretation(category="email"))
    original = ScriptedProvider.ground

    def inspect(self, text, state, material):
        assert [m["section_id"] for m in material] == ["practice-mail:0"]
        assert state.grounding_clarifications == []
        return original(self, text, state, material)

    monkeypatch.setattr(ScriptedProvider, "ground", inspect)
    msg = send(client, sid, "Missing notices in the practice mailbox. Where is the message log?").json()
    assert msg["action"] == "ANSWER" and msg["grounding"]
    snapshot = client.get(f"/api/sessions/{sid}/snapshots").json()[-1]
    assert {g["category"] for g in snapshot["retrieval"]} == {"email"}
