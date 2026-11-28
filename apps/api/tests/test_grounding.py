import json

import pytest

from app.config import settings
from app.evidence import admit_facts, verify_memory
from app.grounding import Citation, GroundedAnswer, Statement, validate_answer
from app.llm import strict_json_schema
from app.models import Interpretation, State
from app.service import merge, restore_issue


@pytest.mark.parametrize(
    "value,quote,text,accepted",
    [
        ("Windows", "", "My Wi-Fi will not connect.", False),
        ("Windows", "Windows", "My Wi-Fi will not connect.", False),
        ("Windows", "Windows", "I'm not using Windows.", False),
        ("macOS", "my MacBook", "Actually, it is my MacBook.", True),
        ("Windows", "Windows", "It happens on Windows.", True),
    ],
)
def test_only_supported_platform_facts_enter_retrieval_state(value, quote, text, accepted):
    raw = Interpretation(
        details={"os": value}, detail_evidence=[{"field": "os", "quote": quote}] if quote else []
    )
    extracted, uncertain = admit_facts(raw, text)
    assert extracted.details.os == (value if accepted else None)
    assert ("os" in uncertain) is not accepted


def test_evidence_schema_survives_strict_provider_conversion():
    schema = strict_json_schema(Interpretation)
    assert schema["$defs"]["DetailEvidence"]["properties"]["quote"]["type"] == "string"
    assert schema["properties"]["detail_evidence"]["type"] == "array"


def test_legacy_or_unbound_memory_cannot_drive_a_pinned_procedure():
    state = State(
        details={"os": "Windows"},
        active_guide="windows-check",
        last_guide="windows-check",
        facts={
            "os": {
                "value": "Windows",
                "status": "reported",
                "message_id": "other-session",
                "evidence": "Windows",
            }
        },
    )
    verify_memory(state, {"this-session": "My Wi-Fi does not work."})
    assert state.details.os is None and state.active_guide is None and state.last_guide is None
    assert state.facts["os"]["status"] == "unverified"
    state.details.os = "macOS"
    state.facts["os"] = {
        "value": "macOS",
        "status": "reported",
        "message_id": "this-session",
        "evidence": "my MacBook",
    }
    verify_memory(state, {"this-session": "Actually it is my MacBook."})
    assert state.details.os == "macOS"


def test_grounded_runtime_rejects_classic_three_call_path(monkeypatch):
    monkeypatch.setattr(settings(), "agent_mode", "grounded")
    with pytest.raises(ValueError, match="conversational"):
        settings().validate_pilot()


def test_new_problem_can_suspend_and_resume_confirmed_context(monkeypatch):
    monkeypatch.setattr(settings(), "agent_mode", "grounded")
    monkeypatch.setattr(settings(), "dialogue_mode", "conversational")
    original = State(
        category="wifi_network",
        problem_text="Wi-Fi issue",
        details={"os": "Windows"},
        knowledge_audiences=["campus", "staff"],
    )
    original_id = original.problem_id
    second = merge(
        original, Interpretation(new_problem=True, category="printing"), "New issue: the printer is stuck."
    )
    assert second.problem_id != original_id and second.details.os is None
    assert second.suspended_problems[0]["problem_id"] == original_id
    resumed = restore_issue(second, "issue-1", "Back to my Wi-Fi issue", "Back to my Wi-Fi issue")
    assert resumed.problem_id == original_id and resumed.details.os == "Windows"
    assert resumed.knowledge_audiences == ["campus", "staff"]
    assert resumed.suspended_problems[0]["category"] == "printing"
    assert "suspended_problems" not in resumed.suspended_problems[0]


def test_invalid_resume_does_not_replace_current_issue(monkeypatch):
    monkeypatch.setattr(settings(), "agent_mode", "grounded")
    state = State(problem_text="Current issue")
    assert restore_issue(state, "invented", "Return to my old issue", "Return to my old issue") is None


def material():
    return [
        {
            "section_id": "access:0",
            "text": "The practice network is available to students and staff.",
            "explanation": "",
            "current_steps": [],
        }
    ]


def test_cited_paraphrase_keeps_exact_reviewable_support():
    answer = GroundedAnswer(
        status="answer",
        statements=[
            Statement(
                text="Both students and staff can use the practice network.",
                citations=[
                    Citation(
                        section_id="access:0",
                        quote="The practice network is available to students and staff.",
                    )
                ],
            )
        ],
    )
    assert validate_answer(answer, material()) == answer


@pytest.mark.parametrize(
    "mutation", ["invented_source", "invented_quote", "operational_instruction", "empty_answer"]
)
def test_rejects_unverifiable_source_response(mutation):
    answer = GroundedAnswer(
        status="answer",
        statements=[
            Statement(
                text="Students can use the practice network.",
                citations=[Citation(section_id="access:0", quote=material()[0]["text"])],
            )
        ],
    )
    if mutation == "invented_source":
        answer.statements[0].citations[0].section_id = "private:0"
    elif mutation == "invented_quote":
        answer.statements[0].citations[0].quote = "The university requires disabling its security tools."
    elif mutation == "operational_instruction":
        answer.statements[0].text = "Disable the firewall."
    else:
        answer.statements = []
    with pytest.raises(ValueError):
        validate_answer(answer, material())


def test_schema_contains_no_unbounded_provider_objects():
    # Strict providers reject unconstrained dict objects; nested citations need
    # explicit properties and required lists as well as top-level validation.
    schema = strict_json_schema(GroundedAnswer)
    for definition in schema["$defs"].values():
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])
    assert len(json.dumps(schema)) < 5000


@pytest.mark.parametrize(
    ("step", "message", "expected"),
    [
        ("reconnect", "I didn't reconnect.", False),
        ("I haven't tried reconnecting", "I haven't tried reconnecting.", False),
        ("reconnect", "I am going to reconnect.", False),
        ("reconnected", "I disconnected and reconnected once; it still failed.", True),
        ("I restarted it", "I didn't reconnect, but I restarted it.", True),
    ],
)
def test_attempts_require_a_report_of_performed_work(step, message, expected):
    from app.service import reported_step

    assert reported_step(step, message) is expected
