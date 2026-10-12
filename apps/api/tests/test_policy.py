import pytest
from pydantic import ValidationError
from app.models import Guide, Interpretation, State
from app.policy import decide
from app.service import merge
from app.llm import ScriptedProvider
from app.privacy import redact


def guide(id="mac", score=0.8, os="macOS", category="wifi_network", network="demo-campus"):
    return Guide(
        id=id,
        source_id=id,
        title="Synthetic",
        category=category,
        source_url="demo://" + id,
        corpus_version="test",
        heading="Test",
        section_text="Test",
        steps=["Open Wi-Fi settings."],
        applicability={"os": os, "network": network},
        score=score,
    )


def state(**kw):
    return State(category="wifi_network", details={"os": "macOS", "network": "demo-campus"}, **kw)


@pytest.mark.parametrize(
    "score,action,rule,warning",
    [
        (0.8, "ANSWER", "high_match", False),
        (0.75, "ANSWER", "high_match", False),
        (0.74, "ANSWER", "provisional_match", True),
        (0.55, "ANSWER", "provisional_match", True),
        (0.54, "HANDOFF", "low_match", False),
    ],
)
def test_score_tiers(score, action, rule, warning):
    d = decide(state(), Interpretation(), [guide(score=score)])
    assert (d.action, d.rule, d.warning) == (action, rule, warning)


def test_human_precedes_unknown_and_cap():
    assert (
        decide(State(questions=["os"] * 3), Interpretation(requested_human=True), []).rule
        == "explicit_human_request"
    )


def test_unknown_and_cap():
    assert decide(State(), Interpretation(), []).field == "category"
    assert decide(State(questions=["category"] * 3), Interpretation(), []).rule == "question_cap"


def test_disagreement_and_cap():
    candidates = [guide(), guide("win", os="Windows")]
    s = State(category="wifi_network", details={"network": "demo-campus"})
    assert decide(s, Interpretation(), candidates).field == "os"
    s.questions = ["os"] * 3
    assert decide(s, Interpretation(), candidates).rule == "question_cap"


def test_most_discriminating_and_no_irrelevant_question():
    candidates = [guide(), guide("win", os="Windows"), guide("linux", os="Linux")]
    assert decide(State(category="wifi_network"), Interpretation(), candidates).field == "os"
    assert decide(state(), Interpretation(), candidates).action == "ANSWER"


def test_known_incompatible_never_answers():
    assert decide(state(), Interpretation(), [guide(os="Windows")]).rule == "no_compatible_guide"


def test_two_failures_and_no_repeat():
    assert decide(state(failures=2), Interpretation(), [guide()]).rule == "repeated_failure"
    assert (
        decide(state(failures=1, attempted_guides=["mac"]), Interpretation(), [guide()]).rule
        == "no_untried_guide"
    )


def test_equivalent_unrestricted_steps_need_no_question():
    s = State(category="wifi_network", details={"network": "demo-campus"})
    assert decide(s, Interpretation(), [guide(), guide("any", os="any")]).action == "ANSWER"


def test_baseline_ignores_disagreement_but_never_fabricates_source():
    d = decide(State(), Interpretation(), [guide()], mode="baseline")
    assert d.action == "ANSWER" and d.guide_id == "mac"
    assert decide(State(), Interpretation(), [], mode="baseline").guide_id is None


def test_corrections_replace_and_new_problem_resets():
    s = state(questions=["os"], failures=1)
    s = merge(s, Interpretation(details={"os": "Windows"}), "Actually Windows")
    assert s.details.os == "Windows" and s.questions == ["os"]
    s = merge(s, Interpretation(category="printing", new_problem=True), "New problem with printer")
    assert s.category == "printing" and s.questions == [] and s.failures == 0 and s.details.os is None


def test_failure_count_is_idempotent():
    s = state(last_answer_id="a", last_guide="mac", last_steps=["step"])
    for _ in range(3):
        s = merge(s, Interpretation(outcome="failed"), "No")
    assert s.failures == 1 and s.steps_tried == ["step"]


def test_extraction_schema_and_unknown_details():
    with pytest.raises(ValidationError):
        Interpretation(details={"os": "imaginary"})
    s = ScriptedProvider().interpret("Wi-Fi isn't working.", State())
    assert s.category == "wifi_network" and s.details.os is None
    assert ScriptedProvider().interpret("Actually Windows, not macOS", State()).details.os == "Windows"


@pytest.mark.parametrize(
    "text",
    [
        "hello jane@example.com",
        "phone 617-555-1234",
        "student 123456789",
        "password=hunter2",
        "api_key: secret123",
    ],
)
def test_redaction(text):
    assert redact(text) != text


def test_grounded_wording_rejects_model_invented_steps(monkeypatch):
    from app.llm import GeminiProvider, ProviderError, Wording
    from app.models import Decision

    monkeypatch.setattr(
        GeminiProvider, "call", lambda *a: Wording(question="Invented instructions", step_indexes=[99])
    )
    with pytest.raises(ProviderError, match="Invalid grounded"):
        GeminiProvider().word(Decision(action="ANSWER", rule="test", guide_id="mac"), guide())
    monkeypatch.setattr(
        GeminiProvider, "call", lambda *a: Wording(question="Send your password", step_indexes=[])
    )
    assert (
        GeminiProvider().word(Decision(action="ASK", rule="test", field="os"), None)
        == "Which operating system are you using?"
    )


@pytest.mark.parametrize(
    "text", ["My MacBook cannot connect to demo-campus Wi-Fi", "Wi-Fi fails after a BIOS update"]
)
def test_device_and_substrings_do_not_confirm_os(text):
    extracted = ScriptedProvider().interpret(text, State())
    assert extracted.details.os is None
    if "MacBook" in text:
        assert extracted.details.device == "laptop"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("My Wi-Fi is broken. I do not want a ticket.", False),
        ("I don't need a human", False),
        ("I already have a ticket", False),
        ("What does a technician do?", False),
        ("I want to talk to TechSpot staff.", True),
        ("Please create a ticket", True),
        ("Technician please", True),
        ("That did not work, I want a human", True),
        ("I don't want a ticket but I need a human", True),
    ],
)
def test_human_request_requires_affirmative_intent(text, expected):
    from app.llm import explicit_human

    assert explicit_human(text) is expected


def test_error_update_preserves_failure_attribution_and_reopens():
    s = state(last_answer_id="a", last_guide="mac", last_steps=["step"], outcome="resolved")
    s.details.error_text = "old error"
    s = merge(s, Interpretation(outcome="failed", details={"error_text": "new error"}), "No, new error")
    assert s.failures == 1 and s.attempted_guides == ["mac"] and s.outcome == "open"
    assert s.last_answer_id == "a" and s.details.error_text == "new error"
    s = merge(s, Interpretation(outcome="failed"), "Still broken")
    assert s.failures == 1


def test_login_failure_followup_retains_email_context():
    s = State(category="email", details={"system_or_app": "Demo-Mail"}, last_answer_id="a", last_guide="mail")
    text = "No, I still cannot log in."
    extracted = ScriptedProvider().interpret(text, s)
    s = merge(s, extracted, text)
    assert s.category == "email" and s.details.system_or_app == "Demo-Mail" and s.failures == 1
    extracted = ScriptedProvider().interpret("New issue: my Demo-Account login is broken", s)
    s = merge(s, extracted, "New issue")
    assert s.category == "account_login" and s.failures == 0


def test_state_owner_preserves_failure_context_even_if_extractor_recategorizes():
    s = State(category="email", details={"system_or_app": "Demo-Mail"}, last_answer_id="a", last_guide="mail")
    s = merge(s, Interpretation(category="account_login", outcome="failed"), "Still cannot log in")
    assert s.category == "email" and s.details.system_or_app == "Demo-Mail" and s.failures == 1
