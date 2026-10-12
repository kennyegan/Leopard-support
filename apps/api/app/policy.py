from .models import Decision, Guide, Interpretation, State
from .workflow import install_question, pending_decision, relevant_to_task

ORDERS = {
    "wifi_network": ["os", "network"],
    "printing": ["os", "printer"],
    "account_login": ["system_or_app"],
    "email": ["system_or_app", "os"],
    "software": ["system_or_app", "os"],
}


def compatible(g: Guide, state: State) -> bool:
    return g.category == state.category and all(
        value == "any" or getattr(state.details, field, None) in (None, value)
        for field, value in g.applicability.items()
    )


def discriminators(guides: list[Guide], state: State) -> list[str]:
    relevant = [g for g in guides if compatible(g, state)]
    fields = ORDERS.get(state.category, [])
    # A constrained field is essential even if only one retrieved value exists.
    # Equivalent steps do not justify an extra question when an unrestricted guide exists.
    missing = []
    for field in fields:
        if getattr(state.details, field) is not None:
            continue
        values = {g.applicability.get(field, "any") for g in relevant} - {"any"}
        unrestricted = [g for g in relevant if g.applicability.get(field, "any") == "any"]
        if values and not (unrestricted and all(g.steps == unrestricted[0].steps for g in relevant)):
            missing.append((field, len(values)))
    return [f for f, _ in sorted(missing, key=lambda item: (-item[1], fields.index(item[0])))]


def decide(
    state: State,
    extracted: Interpretation,
    guides: list[Guide],
    *,
    mode="policy",
    high=0.75,
    low=0.55,
    conversational=False,
    active=None,
) -> Decision:
    if mode == "baseline":
        # Same retrieval; no policy clarification or compatibility filtering.
        return Decision(
            action="ANSWER",
            rule="baseline_closest" if guides else "baseline_empty",
            guide_id=guides[0].id if guides else None,
        )
    if conversational:
        return conversational_decision(state, extracted, guides, high=high, low=low, active=active)
    if extracted.requested_human:
        return Decision(action="HANDOFF", rule="explicit_human_request")
    if state.category is None:
        if len(state.questions) >= 3:
            return Decision(action="HANDOFF", rule="question_cap")
        return Decision(
            action="ASK",
            rule="category_unknown",
            field="category",
            options=["Wi-Fi", "Account login", "Printing", "Email", "Software", "Other"],
        )
    if state.failures >= 2:
        return Decision(action="HANDOFF", rule="repeated_failure")
    if extracted.unsupported or state.category == "other":
        return Decision(action="HANDOFF", rule="unsupported_scope")
    candidates = [g for g in guides if compatible(g, state) and g.source_id not in state.attempted_guides]
    missing = discriminators(candidates, state)
    if missing:
        if len(state.questions) >= 3:
            return Decision(action="HANDOFF", rule="question_cap")
        field = missing[0]
        choices = sorted(
            {g.applicability[field] for g in candidates if g.applicability.get(field, "any") != "any"}
        )
        return Decision(
            action="ASK", rule="missing_discriminator", field=field, options=choices + ["Not sure"]
        )
    if not candidates:
        return Decision(
            action="HANDOFF", rule="no_untried_guide" if state.failures else "no_compatible_guide"
        )
    best = max(candidates, key=lambda g: g.score)
    if best.score >= high:
        return Decision(action="ANSWER", rule="high_match", guide_id=best.id)
    if best.score >= low:
        return Decision(action="ANSWER", rule="provisional_match", guide_id=best.id, warning=True)
    return Decision(action="HANDOFF", rule="low_match")


def conversational_decision(state, extracted, guides, *, high=0.75, low=0.55, active=None):
    """Own the next action; the model supplies facts and wording candidates only."""
    if extracted.requested_human:
        return Decision(action="HANDOFF", rule="explicit_human_request")
    if extracted.unsupported:
        return Decision(action="HANDOFF", rule="unsupported_scope")
    if state.outcome == "resolved":
        return Decision(action="ANSWER", rule="resolved", response_kind="status")
    if extracted.step_result == "blocked":
        # A reported access/product blocker can precede the first graph node.
        return Decision(action="HANDOFF", rule="step_blocked")
    if state.failures >= 2:
        return Decision(action="HANDOFF", rule="repeated_failure")
    if extracted.intent == "thanks":
        return Decision(action="ANSWER", rule="acknowledgement", response_kind="status")
    if extracted.intent == "explain":
        if state.last_question_field:
            return Decision(
                action="ASK",
                rule="clarify_question",
                field=state.last_question_field,
                response_kind="explanation",
            )
        if state.last_guide:
            return Decision(action="ANSWER", rule="explain_previous", response_kind="explanation")

    pending = pending_decision(state, extracted, active)
    if pending:
        return pending
    prerequisite = install_question(state, guides)
    if prerequisite:
        return prerequisite

    blocked = set(state.questions) | set(state.unavailable_details)

    def ask(field, rule):
        if len(state.questions) >= 3 or field in blocked:
            return Decision(action="HANDOFF", rule="question_cap")
        options = {
            "os": ["Windows", "macOS", "Android", "iOS"],
            "device": ["Laptop", "Desktop", "Phone", "Tablet"],
        }.get(field, [])
        return Decision(
            action="ASK",
            rule=rule,
            field=field,
            options=options + (["I'm not sure"] if field not in ("symptom", "category") else []),
        )

    if state.category is None:
        for field in ("category", "symptom", "device"):
            if field not in blocked and (field == "category" or not getattr(state.details, field)):
                return ask(field, "understand_issue")
        return Decision(action="HANDOFF", rule="question_cap")
    if extracted.intent == "vague_issue" and not state.details.symptom and "symptom" not in blocked:
        return ask("symptom", "understand_symptom")

    candidates = [
        g
        for g in guides
        if compatible(g, state)
        and relevant_to_task(g, state)
        and g.source_id not in state.attempted_guides + state.completed_guides
    ]
    complete = [
        g
        for g in candidates
        if all(v == "any" or getattr(state.details, k, None) == v for k, v in g.applicability.items())
    ]
    eligible = [g for g in complete if g.score >= low]
    if eligible:
        best = max(eligible, key=lambda g: g.score)
        if not best.workflow and best.source_id == state.last_guide:
            return Decision(
                action="ANSWER",
                rule="installation_wait" if state.request_type == "install" else "await_guide_result",
                response_kind="status",
                options=["I want a person"]
                if state.request_type == "install"
                else ["Explain this step", "Still not working", "I want a person"],
            )
        return Decision(
            action="ANSWER",
            rule="high_match" if best.score >= high else "provisional_match",
            guide_id=best.id,
            warning=best.score < high,
        )
    # Ask only for facts needed by a plausible guide; never repeat an unanswered
    # field. An unavailable OS must not silently select an OS-specific guide.
    for guide in sorted(candidates, key=lambda g: -g.score):
        if guide.score < low:
            continue
        missing = [
            k
            for k, v in guide.applicability.items()
            if v != "any" and getattr(state.details, k, None) is None
        ]
        if any(k in blocked for k in missing):
            continue
        if missing:
            field = next((f for f in ORDERS.get(state.category, []) if f in missing), missing[0])
            return ask(field, "missing_discriminator")
    if state.failures:
        return Decision(action="HANDOFF", rule="no_untried_guide")
    if state.request_type != "troubleshoot":
        return Decision(action="HANDOFF", rule="task_not_documented")
    # An unfamiliar issue still gets useful intake rather than an abrupt refusal.
    for field in ("symptom", "device", "error_text"):
        if field not in blocked and not getattr(state.details, field):
            return ask(field, "document_unfamiliar_issue")
    return Decision(action="HANDOFF", rule="no_compatible_guide" if not candidates else "low_match")
