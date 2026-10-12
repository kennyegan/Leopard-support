from uuid import uuid4
import hashlib
import json
from pydantic import ValidationError
from psycopg.types.json import Jsonb
from .config import settings, build_revision
from .llm import ProviderError, explicit_human, explicit_stop, provider
from .models import Decision, Interpretation, State, Guide
from .policy import compatible, decide, discriminators
from .privacy import redact, redact_values
from .retrieval import corpus_version, retrieve, load_guide, load_active
from .dialogue import wording as conversation_wording
from .skills import troubleshooting_skill
from .workflow import advance, clear_workflow, contextual_reply, relevant_to_task


def failed_attempt(state):
    if state.last_answer_id and state.last_answer_id not in state.failed_answer_ids:
        state.failed_answer_ids.append(state.last_answer_id)
        state.failures += 1
        if state.last_guide and state.last_guide not in state.attempted_guides:
            state.attempted_guides.append(state.last_guide)
        state.steps_tried = list(dict.fromkeys(state.steps_tried + state.last_steps))
    state.pending_failure = False


def merge(state, extracted, text):
    conversational = settings().dialogue_mode == "conversational"
    if conversational and extracted.intent in ("thanks", "greeting") and (
        extracted.step_result != "unknown" or extracted.outcome != "unknown"
    ):
        # Substantive progress takes precedence over a polite acknowledgement.
        extracted.intent = "support"
    meta_reply = conversational and extracted.intent in ("explain", "thanks", "greeting")
    if conversational:
        contextual_reply(state, extracted, text)
        if extracted.step_result in ("blocked", "not_tried"):
            # Do not attribute displayed steps to a user who could not try them.
            extracted.steps_tried = []
    if meta_reply:
        # A request for explanation/acknowledgement is not evidence of action.
        extracted.outcome = "unknown"
        extracted.step_result = "unknown"
        extracted.installation_stage = None
        extracted.observation = ""
        extracted.steps_tried = []
    # A failure report continues the current problem unless the user explicitly
    # starts another one, even if the extractor recategorizes generic wording.
    continuing_failure = (
        extracted.outcome == "failed" or state.pending_failure
    ) and not extracted.new_problem
    changed_task = (
        conversational
        and not meta_reply
        and not continuing_failure
        and extracted.request_type
        and extracted.request_type != state.request_type
        and extracted.category
        and state.category
        and extracted.category != state.category
    )
    if (
        extracted.new_problem
        or changed_task
        or (
            not conversational
            and extracted.category
            and state.category
            and extracted.category != state.category
            and not continuing_failure
        )
    ):
        state = State(problem_text=text)
    workflow_context = conversational and bool(state.active_guide)
    if extracted.request_type and conversational and not meta_reply:
        if extracted.request_type != state.request_type:
            clear_workflow(state)
            state.questions = []
            state.last_question_field = None
            state.outcome = "open"
            workflow_context = False
        state.request_type = extracted.request_type
    if not state.problem_text:
        state.problem_text = text
    if (
        extracted.category
        and not meta_reply
        and (
            not state.category
            or extracted.new_problem
            or (not conversational and not continuing_failure)
            or extracted.category == state.category
        )
    ):
        state.category = extracted.category
    if (
        workflow_context
        and state.active_kind == "action"
        and not state.active_graph
        and extracted.step_result not in ("blocked", "not_tried", "completed")
        and (extracted.outcome == "failed" or extracted.step_result == "failed" or state.pending_failure)
    ):
        failed_attempt(state)
        clear_workflow(state)
        workflow_context = False
        state.outcome = "open"
    # Attribute a reported failure to the answer the user actually received,
    # before new error details or setup corrections can replace its context.
    if (extracted.outcome == "failed" or state.pending_failure) and not workflow_context:
        failed_attempt(state)
        state.outcome = "open"
    updates = {} if meta_reply else {k: v for k, v in extracted.details.model_dump().items() if v is not None}
    # Explicit corrections replace previous values, and update the semantic query.
    corrected = any(
        k not in ("error_text", "symptom") and getattr(state.details, k) not in (None, v)
        for k, v in updates.items()
    )
    if corrected:
        state.problem_text = f"{state.category or ''} {text}"
        state.last_answer_id = None
        state.last_guide = None
        clear_workflow(state)
        state.completed_guides = []
        workflow_context = False
        state.outcome = "open"
    state.details = state.details.model_copy(update=updates)
    state.steps_tried = list(
        dict.fromkeys(state.steps_tried + [redact(s)[:300] for s in extracted.steps_tried])
    )
    state.uncertainties = [redact(x)[:300] for x in extracted.uncertainties]
    if conversational:
        state.unavailable_details = list(
            dict.fromkeys(
                state.unavailable_details
                + (extracted.unavailable_details if extracted.intent == "unsure" else [])
            )
        )
        state.unavailable_details = [
            f for f in state.unavailable_details if getattr(state.details, f, None) is None
        ]
        if extracted.summary and not meta_reply and extracted.outcome == "unknown":
            state.problem_text = redact(extracted.summary)
        if state.outcome == "handoff":
            state.outcome = "open"
    if workflow_context and not meta_reply:
        if state.active_graph and state.pending_failure and extracted.step_result == "unknown":
            extracted.step_result = "failed"
        handled = advance(state, extracted)
        if handled:
            state.pending_failure = False
            if extracted.outcome == "failed":
                extracted.outcome = "unknown"
        elif extracted.step_result == "failed" or extracted.outcome == "failed" or state.pending_failure:
            failed_attempt(state)
            clear_workflow(state)
            state.outcome = "open"
    if extracted.outcome == "resolved":
        state.outcome = "resolved"
    return state


def ticket_text(state):
    details = "\n".join(f"{key}: {value}" for key, value in state.details.model_dump().items() if value)
    return redact(f"""DEMO ticket draft — not submitted
Summary: {state.problem_text}
Category: {state.category or "unknown"}
Request: {state.request_type}
Observed results: {"; ".join(state.observations) or "None reported"}
Pending check: {state.active_prompt or "None"}
{details}
Attempted steps: {"; ".join(state.steps_tried) or "None reported"}
Guide IDs: {", ".join(dict.fromkeys(state.attempted_guides + ([state.last_guide] if state.last_guide else []))) or "None"}
Unsuccessful solutions: {state.failures}
Please review and remove personal information before sharing.""")


def ensure_ticket(conn, session_id, state):
    row = conn.execute(
        """INSERT INTO tickets(id,session_id,draft_redacted,problem_id) VALUES(%s,%s,%s,%s)
      ON CONFLICT(session_id,problem_id) DO UPDATE SET draft_redacted=CASE WHEN tickets.edited AND tickets.problem_id IS NOT DISTINCT FROM EXCLUDED.problem_id THEN tickets.draft_redacted
      ELSE EXCLUDED.draft_redacted END, edited=tickets.edited AND tickets.problem_id IS NOT DISTINCT FROM EXCLUDED.problem_id, problem_id=EXCLUDED.problem_id, updated_at=now() RETURNING *""",
        (uuid4(), session_id, ticket_text(state), state.problem_id),
    ).fetchone()
    return {"id": str(row["id"]), "draft": row["draft_redacted"], "edited": row["edited"]}


def prepare_state(conn, session):
    state = State.model_validate(session["state"])
    conversational = settings().dialogue_mode == "conversational"
    if conversational:
        recent = conn.execute(
            "SELECT role,text_redacted FROM (SELECT role,text_redacted,created_at,id FROM messages WHERE session_id=%s ORDER BY created_at DESC,role ASC,id DESC LIMIT 6) recent ORDER BY created_at,role DESC,id",
            (session["id"],),
        ).fetchall()
        state.recent_dialogue = [
            {"role": row["role"], "content": row["text_redacted"][:700]} for row in recent
        ]
    if settings().app_mode == "pilot":
        # Small authorized catalog of explicit names, not guessed user facts or
        # operational prose. It prevents initial category filtering from hiding
        # a guide merely because the interpreter did not recognize its name.
        state.interpretation_vocabulary = conn.execute(
            """SELECT DISTINCT a.category,p.key AS field,p.value AS name
            FROM sections s JOIN articles a ON a.id=s.article_id AND a.corpus_version=s.corpus_version
            CROSS JOIN LATERAL jsonb_each_text(s.applicability) p
            WHERE s.corpus_version=%s AND a.is_synthetic
              AND a.allowed_visibility='private synthetic pilot'
              AND s.workflow_version IS NOT NULL
              AND p.key IN ('network','printer','system_or_app','vendor') AND p.value<>'any'
            ORDER BY a.category,p.key,p.value LIMIT 40""",
            (settings().corpus_version,),
        ).fetchall()
    active = load_active(conn, state) if conversational else None
    if active:
        state.active_workflow = [step.model_dump() for step in active.workflow]
        state.active_graph = bool(active.workflow_version)
    return state


def turn(conn, session, text, *, prepared=None, interpretation=None, interpretation_error=None):
    text = redact(text.strip())
    state = prepared if prepared is not None else prepare_state(conn, session)
    user_message = dict(id=str(uuid4()), role="user", text=text)
    client = provider()
    conversational = settings().dialogue_mode == "conversational"
    active = load_active(conn, state) if conversational else None
    guides = []
    try:
        if interpretation_error is not None:
            raise interpretation_error
        extracted = (
            interpretation
            if interpretation is not None
            else (
                Interpretation(requested_human=True)
                if conversational and explicit_human(text)
                else (
                    Interpretation(unsupported=True)
                    if settings().app_mode == "pilot" and explicit_stop(text)
                    else Interpretation.model_validate(client.interpret(text, state))
                )
            )
        )
        # Revalidate and redact provider-returned strings before any storage.
        extracted = Interpretation.model_validate(redact_values(extracted.model_dump()))
        state = merge(state, extracted, text)
        if (
            active
            and active.workflow_version
            and state.active_guide
            and (not compatible(active, state) or not relevant_to_task(active, state))
        ):
            clear_workflow(state)
        if settings().app_mode == "pilot":
            for field, value in extracted.details.model_dump().items():
                if value is not None and getattr(state.details, field) == value:
                    prior = state.facts.get(field)
                    if prior and prior["value"] == value:
                        continue
                    state.facts[field] = dict(
                        value=value,
                        status="reported",
                        message_id=user_message["id"],
                        previous=(
                            {k: prior[k] for k in ("value", "message_id")}
                            if prior and prior["value"] != value
                            else None
                        ),
                    )
            for field in set(extracted.unavailable_details) & set(state.unavailable_details):
                state.facts[field] = dict(
                    value=None, status="unknown", message_id=user_message["id"], previous=None
                )
        guides = retrieve(conn, text, state)
        state.missing_details = discriminators(guides, state)
        state.conflicting_guide_ids = [g.id for g in guides if not compatible(g, state)]
        decision = decide(
            state,
            extracted,
            guides,
            mode=session["mode"],
            high=settings().high_score,
            low=settings().low_score,
            conversational=conversational,
            active=active if state.active_guide else None,
        )
        guide = next((g for g in guides if g.id == decision.guide_id), None)
        if not guide and active and active.id == decision.guide_id:
            guide = active
        if guide and guide not in guides:
            guides.append(guide)
        if conversational and decision.rule == "explain_previous":
            prior = conn.execute(
                "SELECT retrieval FROM state_snapshots WHERE message_id=%s", (state.last_answer_id,)
            ).fetchone()
            guide = (
                next(
                    (
                        Guide.model_validate(g)
                        for g in prior["retrieval"]
                        if g["source_id"] == state.last_guide
                    ),
                    None,
                )
                if prior
                else None
            )
            if settings().app_mode != "pilot":
                guide = guide or load_guide(conn, state.last_guide)
            if guide and not compatible(guide, state):
                guide = None
        wording = (
            conversation_wording(decision, extracted, state)
            if conversational
            else (client.word(decision, guide) if decision.action in ("ASK", "ANSWER") else "")
        )
    except (ProviderError, ValidationError) as error:
        extracted = Interpretation(
            requested_human=explicit_human(text), uncertainties=["Interpretation unavailable"]
        )
        decision = Decision(
            action="HANDOFF",
            rule="explicit_human_request" if extracted.requested_human else "interpretation_unavailable",
            response_kind="service_error" if conversational and not extracted.requested_human else None,
        )
        wording, guide = "", None
        if not state.problem_text:
            state.problem_text = text
        if conversational:
            wording = (
                "The demo's authorized AI test budget has been used up. Your message is saved; the project owner needs to authorize more usage before I can continue."
                if getattr(error, "code", "") == "budget_exhausted"
                else "The assistant couldn't interpret that message right now. Your message is saved. Please retry shortly; this service problem doesn't mean your issue requires a technician."
            )
    message_id, snapshot_id = str(uuid4()), str(uuid4())
    selected_steps = guide.steps if guide else []
    progress = None
    if conversational and guide and guide.workflow and decision.rule != "explain_previous":
        if (state.active_guide, state.active_corpus, state.active_section) != (
            guide.source_id,
            guide.corpus_version,
            guide.id,
        ):
            state.active_step = 0
        state.active_guide = guide.source_id
        state.active_corpus = guide.corpus_version
        state.active_section = guide.id
        state.active_workflow_version = guide.workflow_version
        node = guide.workflow[state.active_step]
        state.active_node = node.node_id or None
        state.active_kind = node.kind
        state.active_prompt = node.prompt
        selected_steps = [guide.steps[i] for i in node.indexes]
        decision.response_kind = "check" if node.kind == "observation" else "guide"
        decision.options = node.choices
        progress = dict(
            current=state.active_step + 1, total=len(guide.workflow), kind=node.kind, prompt=node.prompt
        )
    elif conversational and state.active_guide and active:
        progress = dict(
            current=min(state.active_step + 1, len(active.workflow)),
            total=len(active.workflow),
            kind=state.active_kind,
            prompt=state.active_prompt,
        )

    if decision.action == "ASK":
        if decision.rule != "clarify_question":
            state.questions.append(decision.field or "category")
        else:
            state.explanation_count += 1
        state.last_question_field = decision.field
        answer = wording
    elif decision.action == "ANSWER":
        answer = (
            (
                "This is a provisional match. Check the source applies to your setup."
                if decision.warning
                else "Here are the steps from the synthetic guide."
            )
            if guide
            else "No guide material is available to answer this."
        )
        if conversational:
            answer = wording
        state.last_question_field = None
        if guide and decision.rule != "explain_previous":
            state.last_guide, state.last_steps, state.last_answer_id = (
                guide.source_id,
                selected_steps,
                message_id,
            )
    else:
        answer = "A person should help with this issue. Review or edit the draft below; nothing has been submitted."
        if conversational:
            answer = wording
        state.last_question_field = None
        state.outcome = "open" if decision.response_kind == "service_error" else "handoff"
    sources = (
        [
            dict(
                id=guide.source_id,
                section_id=guide.id,
                title=guide.title,
                source_url=guide.source_url,
                href=f"/sources/{guide.source_id}?version={guide.corpus_version}&section={guide.id}",
                corpus_version=guide.corpus_version,
                is_synthetic=guide.is_synthetic,
                score=guide.score,
            )
        ]
        if guide and decision.action == "ANSWER"
        else []
    )
    steps = selected_steps if guide and decision.action == "ANSWER" else []
    if conversational and decision.rule == "explain_previous" and guide:
        indexes = extracted.explanation_step_indexes
        allowed = state.last_steps if guide.workflow else guide.steps
        steps = (
            [allowed[i] for i in indexes]
            if indexes and all(0 <= i < len(allowed) for i in indexes)
            else allowed
        )
        if settings().app_mode == "pilot":
            node = next((n for n in guide.workflow if n.node_id == state.active_node), None)
            if node:
                answer = node.explanation
    response = dict(
        id=message_id,
        snapshot_id=snapshot_id,
        action=decision.action,
        rule=decision.rule,
        text=answer,
        steps=steps,
        response_kind=decision.response_kind
        or (
            "guide" if decision.action == "ANSWER" else "question" if decision.action == "ASK" else "handoff"
        ),
        skill_version=troubleshooting_skill()[1] if conversational else None,
        application_revision=build_revision(),
        interpretation_schema=hashlib.sha256(
            json.dumps(Interpretation.model_json_schema(), sort_keys=True).encode()
        ).hexdigest()[:12],
        sources=sources,
        options=decision.options,
        progress=progress,
        references=[ref.model_dump() for ref in guide.references] if guide else [],
        request_type=state.request_type,
        question_field=decision.field,
        warning=decision.warning,
        provider=client.name,
        corpus_version=guide.corpus_version if guide else (state.active_corpus or corpus_version()),
        state=state.model_dump(),
    )
    if decision.action == "HANDOFF" and decision.response_kind != "service_error":
        response["ticket"] = ensure_ticket(conn, session["id"], state)
    response["user_message"] = user_message
    conn.execute(
        "INSERT INTO messages(id,session_id,role,text_redacted) VALUES(%s,%s,%s,%s)",
        (user_message["id"], session["id"], "user", text),
    )
    conn.execute(
        "INSERT INTO messages(id,session_id,role,text_redacted,response) VALUES(%s,%s,%s,%s,%s)",
        (message_id, session["id"], "assistant", answer, Jsonb(response)),
    )
    conn.execute(
        """INSERT INTO state_snapshots(id,session_id,message_id,state_json,interpretation,decision,retrieval,provider,corpus_version)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            snapshot_id,
            session["id"],
            message_id,
            Jsonb(state.model_dump()),
            Jsonb(extracted.model_dump()),
            Jsonb(decision.model_dump()),
            Jsonb([g.model_dump() for g in guides]),
            client.name,
            response["corpus_version"],
        ),
    )
    conn.execute(
        "UPDATE sessions SET state=%s, updated_at=now(),revision=revision+1 WHERE id=%s",
        (Jsonb(state.model_dump()), session["id"]),
    )
    return response
