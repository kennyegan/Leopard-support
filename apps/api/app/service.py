from dataclasses import dataclass, field
from fastapi import HTTPException
from uuid import uuid4
import hashlib
import json
from pydantic import ValidationError
from psycopg.types.json import Jsonb
from .config import settings, build_revision
import logging
import re

from .llm import (
    FallbackProvider,
    ProviderError,
    ScriptedProvider,
    explicit_human,
    local_interpretation,
    provider,
)
from .models import Decision, Interpretation, State, Guide
from .policy import compatible, decide, discriminators
from .privacy import redact, redact_values
from .retrieval import corpus_version, retrieve, load_guide, load_active
from .dialogue import QUESTIONS, wording as conversation_wording
from .skills import troubleshooting_skill
from .workflow import advance, clear_workflow, contextual_reply, relevant_to_task
from .knowledge import ACCESS_SQL, access_params, audiences_for
from .evidence import admit_facts, verify_memory
from .grounding import reading_material, validate_answer


def reported_step(step, text):
    # A model may select a reported action, but the words must come from its user turn.
    if not step.strip():
        return False
    for match in re.finditer(r"(?<!\w)" + re.escape(step.strip()) + r"(?!\w)", text, re.I):
        prefix = re.split(r"[.!?;,]|\bbut\b", text[: match.start()], flags=re.I)[-1]
        lead = (prefix + " " + step).strip().replace("’", "'")
        if re.search(
            r"\b(?:did not|didn't|haven't|have not|never|going to|about to|should I|what if)\s+(?:try\s+)?$",
            prefix.strip(),
            re.I,
        ):
            continue
        if re.match(
            r"(?:I )?(?:did not|didn't|haven't|have not|never|will|might|plan to|am going to)\b", lead, re.I
        ):
            continue
        return True
    return False


def failed_attempt(state):
    if state.last_answer_id and state.last_answer_id not in state.failed_answer_ids:
        state.failed_answer_ids.append(state.last_answer_id)
        state.failures += 1
        if state.last_guide and state.last_guide not in state.attempted_guides:
            state.attempted_guides.append(state.last_guide)
    state.pending_failure = False


def restore_issue(state, alias, evidence, text):
    saved = state.issue_choices().get(alias)
    if not saved or len(evidence.split()) < 2 or evidence.strip().casefold() not in text.casefold():
        return None
    restored = State.model_validate(saved)
    restored.suspended_problems = [
        p for p in state.suspended_problems if p["problem_id"] != restored.problem_id
    ]
    if state.problem_text and state.outcome != "resolved":
        restored.suspended_problems.append(state.model_dump(exclude={"suspended_problems"}))
    restored.knowledge_audiences = state.knowledge_audiences
    restored.awaiting_issue_choice = False
    return restored


def merge(state, extracted, text):
    conversational = settings().dialogue_mode == "conversational"
    audiences = state.knowledge_audiences
    if (
        conversational
        and extracted.intent in ("thanks", "greeting")
        and (extracted.step_result != "unknown" or extracted.outcome != "unknown")
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
        suspended = state.suspended_problems[:]
        if settings().agent_mode == "grounded" and state.problem_text and state.outcome != "resolved":
            suspended.append(state.model_dump(exclude={"suspended_problems"}))
        state = State(problem_text=text, suspended_problems=suspended[-3:], knowledge_audiences=audiences)
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
        dict.fromkeys(state.steps_tried + [s for s in extracted.steps_tried if reported_step(s, text)])
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
    if not workflow_context and not meta_reply and extracted.observation:
        state.observations = list(dict.fromkeys(state.observations + [redact(extracted.observation)[:300]]))[
            -20:
        ]
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
    label = "Support ticket draft" if settings().app_mode == "pilot" else "DEMO ticket draft"
    return redact(f"""{label} — not submitted
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


def verified_session_state(conn, session):
    state = State.model_validate(session["state"])
    if settings().agent_mode == "grounded":
        messages = {
            str(row["id"]): row["text_redacted"]
            for row in conn.execute(
                "SELECT id,text_redacted FROM messages WHERE session_id=%s AND role='user'", (session["id"],)
            ).fetchall()
        }
        attempts = {}
        for row in conn.execute(
            """SELECT s.state_json->>'problem_id' AS issue, s.interpretation->'steps_tried' AS steps,
                      m.response->'user_message'->>'id' AS user_message
               FROM state_snapshots s JOIN messages m ON m.id=s.message_id
               WHERE s.session_id=%s AND jsonb_array_length(s.interpretation->'steps_tried')>0""",
            (session["id"],),
        ):
            source = messages.get(row["user_message"], "")
            attempts.setdefault(row["issue"], set()).update(
                s for s in row["steps"] if reported_step(s, source)
            )
        for previous in state.suspended_problems:
            previous["steps_tried"] = [
                s for s in previous.get("steps_tried", []) if s in attempts.get(previous["problem_id"], ())
            ]
        state.steps_tried = [s for s in state.steps_tried if s in attempts.get(state.problem_id, ())]
        state = verify_memory(state, messages)
        state.suspended_problems = [
            verify_memory(State.model_validate(item), messages).model_dump(exclude={"suspended_problems"})
            for item in state.suspended_problems
        ]
    return state


def saved_draft(conn, session_id, state):
    row = conn.execute(
        "SELECT id,draft_redacted AS draft,edited FROM tickets WHERE session_id=%s AND problem_id=%s",
        (session_id, state.problem_id),
    ).fetchone()
    if not row:
        return None
    draft = row["draft"]
    if settings().agent_mode == "grounded" and not row["edited"]:
        # Earlier releases copied every displayed instruction into this line.
        # Keep the saved contents and limit the attempt list to verified reports.
        prefix, marker, rest = draft.rpartition("\nAttempted steps: ")
        attempts, footer, tail = rest.partition("\nGuide IDs: ")
        if marker and footer:
            reported = [s for s in state.steps_tried if s in attempts]
            draft = prefix + marker + ("; ".join(reported) or "None reported") + footer + tail
    return {"id": str(row["id"]), "draft": draft, "edited": row["edited"]}


def prepare_state(conn, session):
    state = verified_session_state(conn, session)
    if settings().app_mode == "pilot" and session.get("owner_id"):
        owner = conn.execute(
            "SELECT i.knowledge_audiences FROM pilot_users u JOIN pilot_invites i ON i.email=u.email WHERE u.id=%s AND i.active",
            (session["owner_id"],),
        ).fetchone()
        state.knowledge_audiences = audiences_for(owner)
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
            f"""SELECT DISTINCT a.category,p.key AS field,p.value AS name
            FROM sections s JOIN articles a ON a.id=s.article_id AND a.corpus_version=s.corpus_version
            JOIN corpora c ON c.version=s.corpus_version
            CROSS JOIN LATERAL jsonb_each_text(s.applicability) p
            WHERE s.corpus_version=%(corpus)s AND {ACCESS_SQL}
              AND p.key IN ('network','printer','system_or_app','vendor') AND p.value<>'any'
            ORDER BY a.category,p.key,p.value LIMIT 40""",
            dict(**access_params(state.knowledge_audiences), corpus=settings().corpus_version),
        ).fetchall()
    active = load_active(conn, state) if conversational else None
    if active:
        state.active_workflow = [step.model_dump() for step in active.workflow]
        state.active_graph = bool(active.workflow_version)
    return state


def plan_turn(
    conn, session, text, *, prepared=None, interpretation=None, interpretation_error=None, client=None
):
    text = redact(text.strip())
    state = prepared if prepared is not None else prepare_state(conn, session)
    user_message = dict(id=str(uuid4()), role="user", text=text)
    client = client or provider()
    conversational = settings().dialogue_mode == "conversational"
    active = load_active(conn, state) if conversational else None
    guides = []

    def interpret():
        nonlocal client
        try:
            return client.interpret(text, state)
        except ProviderError:
            # A public demo should keep helping while the AI provider is overloaded.
            if (
                settings().app_mode != "demo"
                or not settings().provider_fallback
                or isinstance(client, ScriptedProvider)
            ):
                raise
            logging.getLogger("techspot.llm").warning("provider_fallback provider=%s", client.name)
            client = FallbackProvider(client.name)
            return client.interpret(text, state)

    try:
        if interpretation_error is not None:
            raise interpretation_error
        extracted = interpretation
        if extracted is None and conversational:
            extracted = local_interpretation(text, state)
        if extracted is None:
            extracted = Interpretation.model_validate(interpret())
        # Revalidate and redact provider-returned strings before any storage.
        extracted = Interpretation.model_validate(redact_values(extracted.model_dump()))
        uncertain = {}
        if settings().agent_mode == "grounded":
            labels = state.resume_options()
            selected = labels.get(text) if state.awaiting_issue_choice else None
            resume = selected or extracted.resume_problem_id
            if (
                resume
                or extracted.intent == "resume"
                or extracted.resume_evidence
                or state.awaiting_issue_choice
            ):
                if state.awaiting_issue_choice and text == "Continue current issue":
                    state.awaiting_issue_choice = False
                    return status_plan(
                        state, user_message, client, extracted, "issue_current", issue_recap(state)
                    )
                restored = restore_issue(state, resume, text if selected else extracted.resume_evidence, text)
                if restored is None:
                    state.awaiting_issue_choice = True
                    decision = Decision(
                        action="ASK",
                        rule="choose_issue",
                        response_kind="question",
                        options=[*labels, "Continue current issue"],
                    )
                    return TurnPlan(
                        state,
                        user_message,
                        client,
                        extracted,
                        decision,
                        None,
                        [],
                        "Which issue should we continue?",
                        None,
                    )
                state = restored
                if selected or extracted.intent in ("explain", "resume") and not extracted.requested_human:
                    return status_plan(
                        state, user_message, client, extracted, "issue_resumed", issue_recap(state)
                    )
                extracted.new_problem = False
                extracted.category = state.category
                extracted.request_type = state.request_type
                active = load_active(conn, state)
                if active:
                    state.active_workflow = [node.model_dump() for node in active.workflow]
                    state.active_graph = bool(active.workflow_version)
            if extracted.intent in ("draft_status", "draft_contents", "attempt_history") and not (
                extracted.requested_human or extracted.unsupported
            ):
                return status_plan(state, user_message, client, extracted, extracted.intent, "")
            extracted, uncertain = admit_facts(extracted, text)
        state = merge(state, extracted, text)
        active = load_active(conn, state) if conversational else None
        if active:
            state.active_workflow = [step.model_dump() for step in active.workflow]
            state.active_graph = bool(active.workflow_version)
        if settings().agent_mode == "grounded":
            state.uncertain_facts.update(uncertain)
            for field, value in extracted.details.model_dump().items():
                if value is not None:
                    state.uncertain_facts.pop(field, None)
        if (
            active
            and active.workflow_version
            and state.active_guide
            and (not compatible(active, state) or not relevant_to_task(active, state))
        ):
            clear_workflow(state)
        if settings().app_mode == "pilot" or settings().agent_mode == "grounded":
            for field, value in extracted.details.model_dump().items():
                if value is not None and getattr(state.details, field) == value:
                    prior = state.facts.get(field)
                    if (
                        prior
                        and prior["value"] == value
                        and (
                            settings().agent_mode != "grounded"
                            or (prior.get("status") == "reported" and prior.get("evidence"))
                        )
                    ):
                        continue
                    state.facts[field] = dict(
                        value=value,
                        status="reported",
                        evidence=next((e.quote for e in extracted.detail_evidence if e.field == field), ""),
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
        if active and active.id == decision.guide_id and state.active_guide:
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
            if guide and settings().app_mode == "pilot":
                guide = load_guide(
                    conn,
                    guide.source_id,
                    version=guide.corpus_version,
                    section_id=guide.id,
                    audiences=state.knowledge_audiences,
                )
            if guide and not compatible(guide, state):
                guide = None
            if not guide:
                decision = Decision(action="HANDOFF", rule="source_unavailable")
        if guide:
            # A section ID can exist in several immutable corpus versions. Keep
            # the pinned version unambiguous in both model evidence and citations.
            guides = [g for g in guides if g.id != guide.id] + [guide]
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
    return TurnPlan(state, user_message, client, extracted, decision, guide, guides, wording, active)


@dataclass
class TurnPlan:
    state: State
    user_message: dict
    client: object
    extracted: Interpretation
    decision: Decision
    guide: Guide | None
    guides: list[Guide]
    wording: str
    active: Guide | None
    grounding: list[dict] = field(default_factory=list)
    cited_guides: list[Guide] = field(default_factory=list)
    grounded_attempted: bool = False
    grounding_error: str | None = None


def status_plan(state, message, client, extracted, rule, answer):
    decision = Decision(action="ANSWER", rule=rule, response_kind="status")
    return TurnPlan(state, message, client, extracted, decision, None, [], answer, None)


def issue_recap(state):
    details = ", ".join(str(v) for v in state.details.model_dump().values() if v)
    topic = {"wifi_network": "Wi-Fi", "account_login": "account login"}.get(
        state.category, state.category or "support"
    )
    recap = f"Continuing the {topic} issue."
    if details:
        recap += " Reported details: " + details + "."
    if state.steps_tried:
        recap += " You reported: " + "; ".join(state.steps_tried).rstrip(".") + "."
    if state.observations:
        recap += " Last update: " + state.observations[-1]
    return recap


def ground_plan(plan):
    if plan.grounded_attempted:
        return
    plan.grounded_attempted = True
    if settings().agent_mode != "grounded" or plan.decision.action != "ANSWER" or not plan.guide:
        return
    related = [
        g for g in plan.guides if g.category == plan.guide.category and relevant_to_task(g, plan.state)
    ]
    material = reading_material(related, plan.guide, plan.state)
    blocked = set(plan.state.questions) | set(plan.state.unavailable_details)
    plan.state.grounding_clarifications = (
        [
            dict(field=k, section_id=g.id, title=g.title, documented_value=v)
            for g in related
            for k, v in g.applicability.items()
            if v != "any"
            and k in QUESTIONS
            and k not in blocked
            and getattr(plan.state.details, k, None) is None
        ]
        if len(plan.state.questions) < 3
        else []
    )
    try:
        result = validate_answer(
            plan.client.ground(plan.user_message["text"], plan.state, material),
            material,
            {item["field"] for item in plan.state.grounding_clarifications},
        )
        if result.status == "needs_detail":
            plan.decision = Decision(
                action="ASK",
                rule="source_clarification",
                field=result.clarification_field,
                response_kind="question",
                options=["I'm not sure"],
            )
            plan.wording = QUESTIONS[result.clarification_field]
            plan.guide = None
            return
        if result.status == "insufficient":
            plan.decision = Decision(action="HANDOFF", rule="insufficient_evidence")
            plan.wording = "The available sources do not support a reliable answer to that question. Review the support draft below; nothing has been submitted."
            plan.guide = None
            return
        ids = list(
            dict.fromkeys(c.section_id for statement in result.statements for c in statement.citations)
        )
        if plan.guide.content_kind == "procedure" and plan.guide.id not in ids:
            ids.insert(0, plan.guide.id)
        plan.cited_guides = [next(g for g in plan.guides if g.id == section_id) for section_id in ids]
        if plan.guide.content_kind == "information":
            plan.guide = plan.cited_guides[0]
            plan.decision.guide_id = plan.guide.id
        plan.grounding = [statement.model_dump() for statement in result.statements]
        plan.wording = "\n\n".join(
            statement.text + " " + " ".join(f"[{ids.index(c.section_id) + 1}]" for c in statement.citations)
            for statement in result.statements
        )
    except (ProviderError, ValidationError, ValueError) as error:
        plan.grounding_error = getattr(error, "code", "grounding_invalid")
        plan.decision = Decision(
            action="HANDOFF", rule="grounding_unavailable", response_kind="service_error"
        )
        plan.wording = "I couldn't verify a source-backed answer right now. Your message is saved. You can try again or request a person."
        plan.guide = None
        plan.cited_guides = []
        plan.grounding = []


def turn(conn, session, text, *, prepared=None, interpretation=None, interpretation_error=None, plan=None):
    plan = plan or plan_turn(
        conn,
        session,
        text,
        prepared=prepared,
        interpretation=interpretation,
        interpretation_error=interpretation_error,
    )
    ground_plan(plan)
    state, user_message, client = plan.state, plan.user_message, plan.client
    extracted, decision, guide = plan.extracted, plan.decision, plan.guide
    guides, wording, active = plan.guides, plan.wording, plan.active
    conversational = settings().dialogue_mode == "conversational"
    text = user_message["text"]
    if settings().app_mode == "pilot":
        # Revalidate after the external call: a source can expire or be withdrawn
        # while the model is reading it. Do not commit a response from stale evidence.
        current = prepare_state(conn, session)
        for candidate in guides:
            if not load_guide(
                conn,
                candidate.source_id,
                version=candidate.corpus_version,
                section_id=candidate.id,
                audiences=current.knowledge_audiences,
            ):
                raise HTTPException(
                    409, "Knowledge access changed during this turn. Send a new message to retry."
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
        if decision.rule not in ("clarify_question", "choose_issue"):
            state.questions.append(decision.field or "category")
        else:
            state.explanation_count += 1
        if decision.rule != "choose_issue":
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
        if decision.rule not in (
            "issue_current",
            "issue_resumed",
            "draft_status",
            "draft_contents",
            "attempt_history",
        ):
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
    source_guides = (plan.cited_guides or ([guide] if guide else [])) if decision.action == "ANSWER" else []
    sources = [
        dict(
            id=g.source_id,
            section_id=g.id,
            title=g.title,
            source_url=g.source_url,
            href=f"/sources/{g.source_id}?version={g.corpus_version}&section={g.id}",
            corpus_version=g.corpus_version,
            is_synthetic=g.is_synthetic,
            score=g.score,
        )
        for g in source_guides
    ]
    steps = selected_steps if guide and decision.action == "ANSWER" else []
    if conversational and decision.rule == "explain_previous" and guide:
        indexes = extracted.explanation_step_indexes
        allowed = state.last_steps if guide.workflow else guide.steps
        steps = (
            [allowed[i] for i in indexes]
            if indexes and all(0 <= i < len(allowed) for i in indexes)
            else allowed
        )
        if settings().app_mode == "pilot" and not plan.grounding:
            node = next((n for n in guide.workflow if n.node_id == state.active_node), None)
            if node:
                answer = node.explanation
    saved_ticket = None
    if decision.rule in ("draft_status", "draft_contents", "attempt_history"):
        saved_ticket = saved_draft(conn, session["id"], state)
        answer = (
            "A draft is saved for this issue. This assistant has not submitted it."
            if saved_ticket
            else "There is no saved draft for this issue. This assistant has not submitted a ticket."
        )
        if decision.rule == "attempt_history":
            answer += " Reported attempts: " + ("; ".join(state.steps_tried) or "None reported") + "."
        if saved_ticket and decision.rule != "draft_status":
            answer += "\n\nSaved draft:\n" + saved_ticket["draft"]
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
        grounding=plan.grounding,
        agent_mode=settings().agent_mode,
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
    if saved_ticket:
        response["ticket"] = saved_ticket
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
