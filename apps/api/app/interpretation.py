"""Canonical explicit names and the deliberately limited offline test interpreter."""

import re


def normalize(value):
    app = value.details.system_or_app
    if app and re.sub(r"\s", "", app).lower() == "autodesk":
        value.details.vendor = "Autodesk"
        value.details.system_or_app = None
    elif app and app.lower() in {"autocad", "revit", "fusion", "fusion 360", "autodesk fusion"}:
        value.details.vendor = "Autodesk"
    if value.details.vendor and re.sub(r"\s", "", value.details.vendor).lower() == "autodesk":
        value.details.vendor = "Autodesk"
    if value.request_type == "install":
        value.category = "software"
    return value


def scripted_task(value, text, state):
    t = text.lower()
    acquisition = bool(
        re.search(r"(?:need|want|how|where|help).{0,35}(?:download|install|get)|^(?:download|install)\b", t)
    )
    if acquisition:
        value.request_type = "install"
        value.category = "software"
        value.intent = "support"
    elif re.search(r"(?:set ?up|connect).{0,30}(?:first time|new)|first time.{0,25}(?:wi-fi|wifi)", t):
        value.request_type = "setup"
        value.category = "wifi_network"
        value.intent = "support"
    elif re.search(r"(?:need|request|want).{0,15}access", t) and not state.active_guide:
        value.request_type = "access"
        value.category = "account_login"
    if re.search(r"auto\s?desk", t):
        value.details.vendor = "Autodesk"
        value.category = "software"
    for alias, name in [("autocad", "AutoCAD"), ("revit", "Revit"), ("fusion", "Fusion")]:
        if alias in t:
            value.details.vendor = "Autodesk"
            value.details.system_or_app = name
            value.category = "software"
    if (
        state.last_question_field == "system_or_app"
        and not value.details.system_or_app
        and value.intent != "unsure"
        and len(t.split()) < 5
        and not re.fullmatch(r"laptop|desktop|phone|tablet|windows|macos", t)
    ):
        value.details.system_or_app = text[:100]
    if re.search(r"student|educat|class|course", t):
        value.details.license_route = "education"
    elif re.search(r"already have access|existing (?:license|access)|assigned access", t):
        value.details.license_route = "existing"
    elif "trial" in t:
        value.details.license_route = "trial"
    if re.search(r"not sure|don.t know", t) and state.last_question_field == "license_route":
        value.unavailable_details = ["license_route"]
    if state.active_guide:
        if re.search(r"haven.t tried|not tried", t):
            value.step_result = "not_tried"
            value.outcome = "unknown"
        elif re.search(
            r"can.t (?:do|check)|cannot (?:do|check)|not listed|not approved|permission required|admin.*(?:prompt|password)|blocked",
            t,
        ):
            value.step_result = "blocked"
            value.observation = text[:300]
        elif re.search(r"download(?:ed| complete)|finished download", t):
            value.installation_stage = "downloaded"
            value.step_result = "completed"
        elif re.search(r"installed", t):
            value.installation_stage = "installed"
            value.step_result = "completed"
            if re.search(r"opens|working|launches", t):
                value.outcome = "resolved"
        elif re.search(
            r"(?:can|have) access (?:the|to)|download (?:available|option)|connected|disconnected|drops|one device|only (?:this|my)|other devices|phone works|no status error|service problem",
            t,
        ):
            value.step_result = "completed"
            value.observation = text[:300]
        elif value.outcome == "failed":
            value.step_result = "failed"
    if re.search(r"only (?:this|my) (?:device|laptop)|phone works|just (?:this|my) laptop", t):
        value.details.affected_scope = "one_device"
    elif re.search(r"other devices too|all (?:my )?devices|both.*(?:phone|laptop)|multiple devices", t):
        value.details.affected_scope = "multiple_devices"
    if (
        state.details.device
        and re.search(r"phone works|other devices", t)
        and not re.search(r"actually|switched|different problem", t)
    ):
        value.details.device = state.details.device
    return normalize(value)
