"""Conversation wording around deterministic decisions; never invent guide steps."""

import re
from .privacy import redact
from .config import settings

QUESTIONS = {
    "license_route": "Are you using education access, an existing license or assigned access, or a trial? It is fine if you are not sure.",
    "category": "Tell me what is happening and what you expected to happen.",
    "symptom": "What happens when you try—does it fail to connect, disconnect later, or show an error?",
    "device": "What kind of device are you using?",
    "os": "Which operating system is on that device—for example Windows, macOS, Android or iOS?",
    "network": "Which network are you trying to use? A general description such as home or campus is enough.",
    "system_or_app": "Which app or service is affected?",
    "printer": "Which printer are you trying to use? Please give its display name, without personal details.",
    "error_text": "What does the error or status message say? Leave out personal details and access codes.",
}
HELP = {
    "os": "An operating system is the main software on your device, such as Windows or macOS. You can describe the device instead if you aren't sure.",
    "network": "I mean the connection you're using, such as your home Wi-Fi or a campus network. I don't need its password.",
    "system_or_app": "I mean the name of the app or website where the problem happens.",
    "printer": "I mean the printer name shown in your print dialog or on its display.",
    "symptom": "Describe what you see when you try, rather than guessing the cause. For example, an error message or something that never finishes loading.",
    "device": "A description like laptop, phone, desktop, or tablet is enough.",
    "error_text": "Only the non-sensitive error wording is useful. It's fine to say there is no error message.",
    "category": "You don't need to choose a category. Describe the thing that isn't working in your own words.",
}
HANDOFF = {
    "source_unavailable": "The exact guide used for this conversation is unavailable. I have kept the context for a person to continue safely.",
    "step_blocked": "You cannot complete the current step with the access or setup available. I have included that blocker and the progress so far in the draft.",
    "task_not_documented": "I do not have a verified guide for this requested task and product. I will preserve what you need and the details we know for someone who can confirm the right route.",
    "explicit_human_request": "You asked for a person, so I've prepared a draft with the details we have.",
    "repeated_failure": "Two different approaches haven't resolved this. A person should review the symptoms and steps you've already tried.",
    "unsupported_scope": "This needs help beyond the checks I can safely guide here, such as hands-on or authorized account support.",
    "question_cap": "We still don't have enough detail to choose a reliable next step. I'll put what we know into a draft for a person.",
    "no_untried_guide": "I don't have another suitable documented approach after the steps you've tried. The draft will help a person continue from here.",
    "no_compatible_guide": "The available documentation doesn't cover this setup well enough for me to give specific instructions.",
    "low_match": "I couldn't find sufficiently relevant documentation to recommend a fix confidently.",
}


def safe_prose(text):
    """Allow conversational wording, excluding links, commands and secret requests.

    This is a secondary guard, not a semantic guarantee. Operational steps always
    come from stored sources and user text is privacy-filtered separately.
    """
    # Pilot prose is rendered from reviewed templates/sources. Regexes below
    # remain a secondary demo guard, never a claimed semantic safety boundary.
    if settings().app_mode == "pilot":
        return ""
    text = redact(text).strip()
    if re.search(
        r"https?://|www\.|```|\b(?:sudo|powershell|curl|rm -|format c:|ignore instructions)\b", text, re.I
    ):
        return ""
    if re.search(
        r"\b(?:send|share|paste|provide|tell me|enter|type)\b.{0,35}\b(?:password|secret|token|verification code|student id)\b",
        text,
        re.I,
    ):
        return ""
    if re.search(
        r"\b(?:delete|disable|factory reset|download|install|execute|run the command)\b", text, re.I
    ):
        return ""
    return text


def wording(decision, extracted, state):
    if decision.rule == "graph_intake":
        return decision.question
    if decision.rule == "installation_wait":
        return "That's okay. Use the official reference above or ask whoever requested the software for its exact product name and access route. Tell me what you find, and I'll continue from there."
    if decision.rule == "await_guide_result":
        return "I have kept those details. The current guide is above. Tell me what happened after trying it, or which part you cannot do."

    if decision.rule == "await_result":
        if extracted.step_result == "not_tried":
            return "No problem—nothing has been counted as a failed attempt. The current step is still available above. Tell me what happens when you try it, or ask me to explain it."
        return "I have kept the details you provided. Before moving on, " + (
            state.active_prompt[:1].lower() + state.active_prompt[1:]
            if state.active_prompt
            else "tell me what happened with the current step."
        )
    if decision.rule == "verify_outcome":
        return "The documented steps are complete. Does the task now work as expected, or is something still blocking you?"
    if decision.rule == "next_check":
        return "That result helps narrow down the next step. Continue with this part of the same guide."

    if decision.rule == "resolved":
        return "Glad that worked. I've marked this issue resolved. If something else comes up, describe the new issue here."
    if decision.rule == "acknowledgement":
        return "You're welcome. Let me know what happens when you try the steps, or describe what you need help understanding."
    if decision.rule == "clarify_question":
        return safe_prose(extracted.explanation) or HELP.get(decision.field, HELP["category"])
    if decision.rule == "explain_previous":
        return (
            safe_prose(extracted.explanation)
            or "These are the relevant steps from the guide we were using. This explanation doesn't count as another attempted fix."
        )
    if decision.action == "HANDOFF":
        return (
            HANDOFF.get(decision.rule, HANDOFF["no_compatible_guide"])
            + " Review or edit the draft below; nothing has been submitted."
        )
    acknowledgement = safe_prose(extracted.acknowledgement)
    if "?" in acknowledgement:
        acknowledgement = ""
    if decision.action == "ASK":
        if decision.rule == "installation_detail":
            if decision.field == "system_or_app":
                return (
                    "Autodesk makes several applications. Which one do you need—AutoCAD, Revit, Fusion, or another product?"
                    if state.details.vendor == "Autodesk"
                    else "Which application do you want to download or install?"
                )
            if decision.field == "os":
                return "Which operating system is on the device where you want to install it—Windows, macOS, or something else?"
            return QUESTIONS["license_route"]
        proposed = next((q.text for q in extracted.question_drafts if q.field == decision.field), "")
        question = safe_prose(proposed) if proposed.count("?") <= 1 else ""
        question = question or QUESTIONS.get(decision.field, QUESTIONS["category"])
        if not proposed and decision.field == "symptom" and state.category != "wifi_network":
            question = "What happens when you try, and what did you expect to happen?"
        return " ".join(x for x in [acknowledgement, question] if x)
    if state.request_type == "install":
        return "Let’s work through the download and installation route. These are demonstration instructions with official vendor links; I have not verified your account access."
    prefix = (
        "Here are initial checks from a synthetic guide. Try them when it is safe, then tell me what happens."
    )
    if decision.warning:
        prefix = "This guide may help narrow it down. Check that the steps fit your situation, then tell me what happens."
    return " ".join(x for x in [acknowledgement, prefix] if x)
