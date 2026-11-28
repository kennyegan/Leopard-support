"""Conservative fact admission. Schema-valid guesses must not become retrieval filters."""

import re
from .models import DetailEvidence

ALIASES = {
    "macOS": ["macos", "mac os", "macbook", "imac", "mac"],
    "Windows": ["windows", "win11", "win10"],
    "iOS": ["ios", "iphone"],
    "Android": ["android"],
    "laptop": ["laptop", "macbook", "notebook"],
    "desktop": ["desktop", "imac"],
    "phone": ["phone", "iphone"],
    "education": ["education", "educational", "student license", "academic license"],
    "existing": ["existing license", "already licensed"],
    "trial": ["trial"],
    "one_device": ["only this device", "only my laptop", "one device"],
    "multiple_devices": ["multiple devices", "both devices", "all devices", "every device"],
    "one_app": ["one app", "only this app"],
    "home": ["home", "house"],
}


def positive_literal(value, text):
    for alias in ALIASES.get(value, [value]):
        for match in re.finditer(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.I):
            before = text[max(0, match.start() - 35) : match.start()].lower()
            if not re.search(
                r"(?:not|isn't|isn’t|wasn't|wasn’t|without|don't have|don’t have|rather than)(?:\s+(?:on|using|a|an|running|my))*\s*$",
                before,
            ):
                return True
    return False


def supported_detail(value, quote, text):
    if not quote or len(quote) > 1000 or quote.casefold() not in text.casefold():
        return False
    # Require a value/known normalization in the quoted words AND in a positive
    # mention in the full user message. This checks literal support, not full entailment.
    return positive_literal(value, quote) and positive_literal(value, text)


def admit_facts(extracted, text):
    accepted = extracted.model_copy(deep=True)
    uncertain = {}
    for field, value in extracted.details.model_dump().items():
        if value is None:
            continue
        quote = next((e.quote for e in extracted.detail_evidence if e.field == field), "")
        if not supported_detail(value, quote, text):
            uncertain[field] = {"value": value, "status": "unverified", "evidence": quote[:300]}
            setattr(accepted.details, field, None)
    return accepted, uncertain


def verify_memory(state, messages):
    """Old guided sessions must not smuggle unbound facts into grounded retrieval."""
    from .workflow import clear_workflow

    changed = False
    for name, value in state.details.model_dump().items():
        if value is None:
            continue
        fact = state.facts.get(name, {})
        message = messages.get(str(fact.get("message_id")), "")
        if (
            fact.get("status") == "reported"
            and fact.get("value") == value
            and supported_detail(value, fact.get("evidence", ""), message)
        ):
            continue
        state.uncertain_facts[name] = {"value": value, "status": "unverified", "evidence": ""}
        state.facts[name] = {**fact, "value": value, "status": "unverified"}
        setattr(state.details, name, None)
        changed = True
    if changed:
        clear_workflow(state)
        state.last_guide, state.last_answer_id, state.last_steps = None, None, []
    return state


def literal_evidence(extracted, text):
    """Offline interpreter normalization only; it is not a semantic evaluation."""
    extracted.detail_evidence = [
        DetailEvidence(field=field, quote=text)
        for field, value in extracted.details.model_dump().items()
        if value and positive_literal(value, text)
    ]
    return extracted
