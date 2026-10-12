"""Bounded source-authored diagnostics. No product names or executable content."""

from .models import Details, Decision

RESULTS = {"completed", "failed", "blocked", "unknown", "not_tried"}
TERMINALS = {"@wait", "@verify", "@retrieve", "@handoff", "@retry"}


def validate_graph(guide):
    if not guide.workflow_version:
        return
    nodes = {n.node_id: n for n in guide.workflow}
    if not nodes or len(nodes) != len(guide.workflow) or len(nodes) > 12:
        raise ValueError("Graph requires 1–12 unique nodes")
    fields = set(Details.model_fields)
    for field in guide.routing:
        if field not in fields:
            raise ValueError("Unknown routing field")
    for item in guide.intake:
        if item.field not in fields or not item.prompt:
            raise ValueError("Invalid graph intake")
    edges = {}
    for node in nodes.values():
        if not node.node_id or node.node_id.startswith("@"):
            raise ValueError("Invalid node ID")
        if set(node.transitions) != RESULTS:
            raise ValueError("Every observation outcome needs an explicit transition")
        if node.transitions["not_tried"] != "@wait":
            raise ValueError("Untried checks must not advance")
        if node.transitions["unknown"] not in {"@wait", "@handoff"}:
            raise ValueError("Unknown results cannot establish completion")
        if not node.explanation:
            raise ValueError("Nodes need reviewed explanatory text")
        if any(i < 0 or i >= len(guide.steps) for i in node.indexes):
            raise ValueError("Invalid source step")
        targets = set(node.transitions.values())
        for branch in node.branches:
            if set(branch) != {"field", "equals", "next"} or branch["field"] not in fields:
                raise ValueError("Invalid fact branch")
            targets.add(branch["next"])
        if targets - set(nodes) - TERMINALS:
            raise ValueError("Dangling graph transition")
        if "resolved" in node.replies.values() and (
            node.kind != "action" or node.transitions["completed"] != "@verify"
        ):
            raise ValueError("Only final corrective checks may accept resolution")
        edges[node.node_id] = targets - TERMINALS
    seen, visiting = set(), set()

    def visit(node_id):
        if node_id in visiting:
            raise ValueError("Diagnostic graph contains a cycle")
        if node_id in seen:
            return
        visiting.add(node_id)
        for target in edges[node_id]:
            visit(target)
        visiting.remove(node_id)
        seen.add(node_id)

    visit(guide.workflow[0].node_id)
    if seen != set(nodes):
        raise ValueError("Unreachable diagnostic node")


def matches(guide, state):
    if not all(getattr(state.details, key) in values for key, values in guide.routing.items()):
        return False
    # If an entry observation's evidence is already known and its declared
    # transition requests another guide, do not ask the observation again.
    return not any(
        branch["next"] == "@retrieve" and getattr(state.details, branch["field"]) == branch["equals"]
        for branch in guide.workflow[0].branches
    )


def intake(state, guides):
    # Intake is source-defined; exclude routes contradicted by confirmed facts.
    blocked = set(state.questions) | set(state.unavailable_details)
    for guide in guides:
        if not guide.workflow_version:
            continue
        for item in guide.intake:
            if getattr(state.details, item.field) is None and item.field not in blocked:
                if len(state.questions) >= 3:
                    return Decision(action="HANDOFF", rule="question_cap")
                return Decision(
                    action="ASK",
                    rule="graph_intake",
                    field=item.field,
                    question=item.prompt,
                    options=item.choices + ["I'm not sure"],
                )
    return None


def current(state):
    return next((n for n in state.active_workflow if n["node_id"] == state.active_node), None)


def contextual_reply(state, extracted, text):
    node = current(state)
    if not node:
        return
    reply = text.casefold().strip().rstrip(".!?")
    result = node["replies"].get(reply)
    # A model's generic 'yes means resolved' cannot resolve an intermediate check.
    # An explicit report of whole-task recovery may arrive during observation.
    # Require a literal substantive user quote; bare yes still cannot complete
    # an intermediate check. Installation retains its final launch boundary.
    evidence = extracted.resolution_evidence.casefold().strip()
    reported_recovery = (
        state.request_type != "install" and len(evidence.split()) >= 3 and evidence in text.casefold()
    )
    if extracted.outcome == "resolved" and not (
        reported_recovery or (node["kind"] == "action" and node["transitions"]["completed"] == "@verify")
    ):
        extracted.outcome = "unknown"
    if result:
        extracted.step_result = "completed" if result == "resolved" else result
        extracted.outcome = "resolved" if result == "resolved" else "unknown"
        extracted.observation = text[:300]
        extracted.installation_stage = None


def advance(state, extracted):
    node = current(state)
    if not node:
        return False
    if extracted.observation:
        state.observations = list(dict.fromkeys(state.observations + [extracted.observation]))[-20:]
    target = node["transitions"][extracted.step_result]
    if extracted.step_result not in {"blocked", "not_tried"}:
        for branch in node["branches"]:
            if getattr(state.details, branch["field"]) == branch["equals"]:
                target = branch["next"]
                break
    if target == "@wait":
        state.workflow_waits += 1
        if state.workflow_waits >= 3:
            state.workflow_blocked = True
        return True
    if target == "@handoff":
        state.workflow_blocked = True
        return True
    state.workflow_blocked = False
    state.workflow_waits = 0
    if target == "@retry":
        return False  # Existing bounded failed-attempt accounting chooses another guide.
    if extracted.step_result == "completed":
        state.steps_tried = list(dict.fromkeys(state.steps_tried + state.last_steps))
    state.workflow_advanced = True
    if target == "@retrieve":
        state.completed_guides = list(dict.fromkeys(state.completed_guides + [state.active_guide]))
        state.active_guide = None
        state.active_node = None
    elif target == "@verify":
        state.active_node = None
        state.active_step = len(state.active_workflow)
    else:
        state.active_node = target
        state.active_step = next(i for i, n in enumerate(state.active_workflow) if n["node_id"] == target)
    return True
