"""Source-defined progress; model observations never create operational steps."""

import re

from .models import Decision
from . import graph
from .config import settings


def contextual_reply(state, extracted, text):
    """A short answer belongs to the pending question, not the entire task."""
    if state.active_graph:
        return graph.contextual_reply(state, extracted, text)
    reply = text.lower().strip().rstrip(".!?")
    if reply not in {"yes", "yep", "yeah", "no", "nope"}:
        return
    if not state.active_guide and not state.last_question_field:
        return
    if state.last_question_field:
        # Intake asks for a named detail; "yes" cannot supply a product or OS.
        extracted.details = type(extracted.details)()
        extracted.category = None
        extracted.request_type = None
        extracted.new_problem = False
    # A final action's outcome prompt may legitimately resolve the task.
    if (
        state.active_kind == "action"
        and state.active_workflow
        and state.active_step >= len(state.active_workflow) - 1
        and not state.last_question_field
    ):
        return
    extracted.outcome = "unknown"
    extracted.step_result = "unknown"
    extracted.installation_stage = None
    extracted.observation = ""
    if state.active_kind == "observation" and re.match(
        r"^(?:do you|does|is|are|can you|have you)\b", state.active_prompt, re.I
    ):
        extracted.step_result = "completed" if reply in {"yes", "yep", "yeah"} else "blocked"
        extracted.observation = f"{state.active_prompt} — {text}"


def clear_workflow(state):
    state.active_guide = None
    state.active_corpus = None
    state.active_section = None
    state.active_workflow_version = None
    state.active_node = None
    state.workflow_waits = 0
    state.active_graph = False
    state.active_step = 0
    state.active_kind = None
    state.active_prompt = ""
    state.active_workflow = []
    state.workflow_blocked = False
    state.workflow_advanced = False


def install_question(state, guides=()):
    if settings().app_mode == "pilot":
        relevant = [
            g
            for g in guides
            if g.category == state.category
            and all(
                v == "any" or getattr(state.details, k, None) in (None, v) for k, v in g.applicability.items()
            )
        ]
        question = graph.intake(state, relevant)
        if question:
            return question
        if (
            state.request_type == "install"
            and not state.details.system_or_app
            and "system_or_app" not in set(state.questions) | set(state.unavailable_details)
        ):
            return (
                Decision(action="HANDOFF", rule="question_cap")
                if len(state.questions) >= 3
                else Decision(
                    action="ASK",
                    rule="graph_intake",
                    field="system_or_app",
                    question="Which application do you want to download or install?",
                    options=["I'm not sure"],
                )
            )
        return None
    if state.request_type != "install":
        return None
    blocked = set(state.questions) | set(state.unavailable_details)
    fields = ["system_or_app"]
    if state.details.vendor == "Autodesk" and state.details.system_or_app:
        fields += ["os", "license_route"]
    for field in fields:
        if getattr(state.details, field) is None and field not in blocked:
            if len(state.questions) >= 3:
                return Decision(action="HANDOFF", rule="question_cap")
            options = {
                "system_or_app": ["AutoCAD", "Revit", "Fusion"] if state.details.vendor == "Autodesk" else [],
                "os": ["Windows", "macOS", "Linux"],
                "license_route": ["Student or educator", "I already have access", "Trial"],
            }[field]
            return Decision(
                action="ASK", rule="installation_detail", field=field, options=options + ["I'm not sure"]
            )
    return None


def relevant_to_task(guide, state):
    if state.request_type not in guide.request_types:
        return False
    if guide.workflow_version:
        return graph.matches(guide, state)
    if settings().app_mode == "pilot":
        return False  # Pilot never falls back to legacy product-specific execution.
    if guide.source_id.startswith("autodesk-"):
        if state.details.vendor != "Autodesk":
            return False
        if not state.details.system_or_app:
            return guide.source_id == "autodesk-product"
        if state.details.license_route:
            return guide.source_id == "autodesk-" + state.details.license_route
        return guide.source_id == "autodesk-access-unknown"
    return True


def advance(state, extracted):
    """Apply only an explicit current-step result; observations aren't failed fixes."""
    if state.active_graph:
        return graph.advance(state, extracted)
    if not state.active_guide or not state.active_workflow:
        return False
    if extracted.observation:
        state.observations = list(dict.fromkeys(state.observations + [extracted.observation]))[-20:]
    result = extracted.step_result
    if state.active_kind == "observation" and result == "failed":
        result = "completed"
    if result == "blocked":
        state.workflow_blocked = True
        return True
    if result == "not_tried":
        return True
    if result == "completed" or extracted.installation_stage:
        state.workflow_blocked = False
    if result == "completed":
        state.steps_tried = list(dict.fromkeys(state.steps_tried + state.last_steps))
        state.active_step += 1
        state.workflow_advanced = True
    if extracted.installation_stage:
        for i, step in enumerate(state.active_workflow):
            if step.get("milestone") == extracted.installation_stage:
                state.active_step = max(state.active_step, i + 1)
                state.workflow_advanced = True
    if state.active_guide == "general-wifi" and state.details.affected_scope:
        state.active_step = len(state.active_workflow)
        state.workflow_advanced = True
    if state.active_step >= len(state.active_workflow) and state.active_kind == "observation":
        state.completed_guides = list(dict.fromkeys(state.completed_guides + [state.active_guide]))
        state.active_guide = None
    return state.active_kind == "observation" or result == "completed" or bool(extracted.installation_stage)


def pending_decision(state, extracted, active):
    if state.active_guide and active is None:
        return Decision(action="HANDOFF", rule="source_unavailable")
    if state.workflow_blocked:
        return Decision(action="HANDOFF", rule="step_blocked")
    if not state.active_guide or active is None:
        return None
    if state.active_step >= len(active.workflow):
        return Decision(
            action="ANSWER",
            rule="verify_outcome",
            response_kind="status",
            options=["It's working now", "Still not working", "I want a person"],
        )
    if state.workflow_advanced:
        return Decision(action="ANSWER", rule="next_check", guide_id=active.id)
    return Decision(
        action="ANSWER",
        rule="await_result",
        response_kind="status",
        options=["Explain this step", "I haven't tried it", "I can't do this"],
    )
