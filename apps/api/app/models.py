from typing import Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

RequestType = Literal["troubleshoot", "install", "setup", "access", "how_to"]

Category = Literal["wifi_network", "account_login", "printing", "email", "software", "other"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Details(Strict):
    vendor: str | None = Field(default=None, max_length=100)
    license_route: Literal["education", "existing", "trial"] | None = None
    affected_scope: Literal["one_device", "multiple_devices", "one_app"] | None = None
    network: str | None = Field(default=None, max_length=100)
    device: Literal["laptop", "desktop", "phone", "tablet"] | None = None
    os: Literal["macOS", "Windows", "Linux", "iOS", "Android"] | None = None
    system_or_app: str | None = Field(default=None, max_length=100)
    printer: str | None = Field(default=None, max_length=100)
    error_text: str | None = Field(default=None, max_length=300)
    symptom: str | None = Field(default=None, max_length=300)


class QuestionDraft(Strict):
    field: Literal[
        "category",
        "symptom",
        "device",
        "os",
        "network",
        "system_or_app",
        "printer",
        "error_text",
        "license_route",
    ]
    text: str = Field(max_length=240)


class Interpretation(Strict):
    request_type: RequestType | None = Field(
        default=None,
        description="The user's goal. Keep the existing goal through progress or access blockers. Joining/configuring a network without a reported malfunction is setup.",
    )
    step_result: Literal["unknown", "completed", "failed", "blocked", "not_tried"] = Field(
        default="unknown",
        description="Blocked means the user CANNOT perform a check or obtain the needed access/product, even during intake. Failed means they DID perform a corrective action and it did not help. Never treat inability to access a queue as having tried its steps.",
    )
    observation: str = Field(default="", max_length=300)
    installation_stage: Literal["downloaded", "installed"] | None = None
    category: Category | None = None
    details: Details = Field(default_factory=Details)
    steps_tried: list[str] = Field(default_factory=list, max_length=20)
    outcome: Literal["unknown", "failed", "resolved"] = "unknown"
    resolution_evidence: str = Field(
        default="",
        max_length=300,
        description="Exact quote from the current user message explicitly reporting the whole task now works. Empty for thanks, yes, an intermediate download or merely completing a diagnostic observation.",
    )
    requested_human: bool = False
    unsupported: bool = False
    new_problem: bool = False
    uncertainties: list[str] = Field(default_factory=list, max_length=20)
    intent: Literal["support", "vague_issue", "explain", "unsure", "greeting", "thanks"] = "support"
    summary: str = Field(default="", max_length=350)
    acknowledgement: str = Field(default="", max_length=200)
    question_drafts: list[QuestionDraft] = Field(default_factory=list, max_length=3)
    explanation: str = Field(default="", max_length=350)
    explanation_step_indexes: list[int] = Field(default_factory=list, max_length=6)
    unavailable_details: list[
        Literal[
            "os", "network", "device", "system_or_app", "printer", "error_text", "symptom", "license_route"
        ]
    ] = Field(default_factory=list, max_length=7)


class State(Strict):
    request_type: RequestType = "troubleshoot"
    active_guide: str | None = None
    active_corpus: str | None = None
    active_section: str | None = None
    active_workflow_version: str | None = None
    active_node: str | None = None
    workflow_waits: int = 0
    active_graph: bool = Field(default=False, exclude=True)
    facts: dict[str, dict] = Field(default_factory=dict)
    active_step: int = 0
    active_kind: str | None = None
    active_prompt: str = ""
    completed_guides: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    workflow_blocked: bool = False
    workflow_advanced: bool = Field(default=False, exclude=True)
    active_workflow: list[dict] = Field(default_factory=list, exclude=True)
    problem_id: str = Field(default_factory=lambda: str(uuid4()))
    category: Category | None = None
    details: Details = Field(default_factory=Details)
    steps_tried: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    missing_details: list[str] = Field(default_factory=list)
    conflicting_guide_ids: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    failures: int = 0
    attempted_guides: list[str] = Field(default_factory=list)
    last_guide: str | None = None
    last_steps: list[str] = Field(default_factory=list)
    last_answer_id: str | None = None
    failed_answer_ids: list[str] = Field(default_factory=list)
    pending_failure: bool = False
    outcome: str = "open"
    problem_text: str = ""
    unavailable_details: list[str] = Field(default_factory=list)
    last_question_field: str | None = None
    explanation_count: int = 0
    recent_dialogue: list[dict[str, str]] = Field(default_factory=list, exclude=True)
    interpretation_vocabulary: list[dict[str, str]] = Field(default_factory=list, exclude=True)


class Reference(Strict):
    title: str
    url: str
    checked_at: str


class WorkflowStep(Strict):
    node_id: str = ""
    indexes: list[int] = Field(min_length=1, max_length=6)
    kind: Literal["observation", "action"]
    prompt: str
    choices: list[str] = Field(default_factory=list)
    milestone: Literal["downloaded", "installed"] | None = None
    explanation: str = ""
    risk: Literal["observe", "reversible"] = "observe"
    transitions: dict[str, str] = Field(default_factory=dict)
    replies: dict[str, Literal["completed", "failed", "blocked", "not_tried", "resolved", "unknown"]] = Field(
        default_factory=dict
    )
    branches: list[dict[str, str]] = Field(default_factory=list)


class Intake(Strict):
    field: str
    prompt: str
    choices: list[str] = Field(default_factory=list)


class Guide(Strict):
    workflow_version: str | None = None
    intake: list[Intake] = Field(default_factory=list)
    routing: dict[str, list[str | None]] = Field(default_factory=dict)
    request_types: list[RequestType] = Field(default_factory=lambda: ["troubleshoot"])
    references: list[Reference] = Field(default_factory=list)
    workflow: list[WorkflowStep] = Field(default_factory=list)
    id: str
    source_id: str
    title: str
    category: Category
    source_url: str
    corpus_version: str
    is_synthetic: bool = True
    heading: str
    section_text: str
    steps: list[str] = Field(min_length=1, max_length=6)
    applicability: dict[str, str]
    score: float = 0


class Decision(Strict):
    action: Literal["ANSWER", "ASK", "HANDOFF"]
    rule: str
    field: str | None = None
    question: str | None = None
    options: list[str] = Field(default_factory=list)
    guide_id: str | None = None
    warning: bool = False
    response_kind: (
        Literal["guide", "question", "explanation", "status", "handoff", "service_error", "check"] | None
    ) = None


class SessionIn(Strict):
    mode: Literal["policy", "baseline"] = "policy"


class MessageIn(Strict):
    text: str = Field(min_length=1, max_length=1000)
    request_id: UUID | None = None


class FeedbackIn(Strict):
    session_id: str
    message_id: str
    snapshot_id: str
    kind: Literal["rating", "fix", "question"]
    value: Literal["yes", "no"]
    reason: str = Field(default="", max_length=100)
    comment: str = Field(default="", max_length=500)


class TicketIn(Strict):
    draft: str = Field(max_length=5000)
