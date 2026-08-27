"""Versioned, scenario-neutral contracts for WebAuto v3."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _id() -> str:
    return str(uuid4())


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "1.0"


class RiskLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"

    @property
    def rank(self) -> int:
        return int(self.value[1:])


class IdempotencyClass(str, Enum):
    READ_ONLY = "read_only"
    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"
    UNKNOWN = "unknown"


class Placement(str, Enum):
    DESKTOP_MANAGED = "desktop_managed"
    BROWSER_ATTACH = "browser_attach"
    LOCAL_DEVICE_AGENT = "local_device_agent"
    REMOTE_DEDICATED = "remote_dedicated"


class BrowserFeature(str, Enum):
    DOM = "dom"
    ACCESSIBILITY = "accessibility"
    SCREENSHOT = "screenshot"
    DOWNLOAD = "download"
    UPLOAD = "upload"
    MULTI_PAGE = "multi_page"
    CDP = "cdp"
    PERSISTENT_PROFILE = "persistent_profile"


class AutonomyPolicy(ContractModel):
    max_autonomous_risk: RiskLevel = RiskLevel.L1
    allow_plan_fallback: bool = True
    allow_human_takeover: bool = True
    prohibited_actions: list[str] = Field(default_factory=list)


class RiskBudget(ContractModel):
    max_risk: RiskLevel = RiskLevel.L1
    max_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    max_external_writes: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def amount_has_currency(self) -> RiskBudget:
        if self.max_amount is not None and self.currency is None:
            raise ValueError("currency is required when max_amount is set")
        return self


class GoalContract(ContractModel):
    id: str = Field(default_factory=_id)
    objective: str = Field(min_length=1)
    constraints: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[str] = Field(min_length=1)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    autonomy_policy: AutonomyPolicy = Field(default_factory=AutonomyPolicy)
    risk_budget: RiskBudget = Field(default_factory=RiskBudget)
    deadline: datetime | None = None
    preferred_placement: Placement | None = None

    @model_validator(mode="after")
    def deadline_is_timezone_aware(self) -> GoalContract:
        if self.deadline is not None and self.deadline.tzinfo is None:
            raise ValueError("deadline must include a timezone")
        return self


class CapabilityDefinition(ContractModel):
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str = Field(min_length=1)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    preconditions: list[str] = Field(min_length=1)
    risk_level: RiskLevel
    idempotency: IdempotencyClass
    required_browser_features: set[BrowserFeature] = Field(default_factory=set)
    verifier_kinds: list[str] = Field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return self.name, self.version


class CapabilityNode(ContractModel):
    id: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    capability_version: str = "1.0.0"
    input_mapping: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=1, ge=1, le=20)
    approval_required: bool = False
    human_node: bool = False


class GraphEdge(ContractModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    condition: str = "always"
    priority: int = 0


class CapabilityGraph(ContractModel):
    id: str = Field(default_factory=_id)
    entry_node_id: str
    nodes: list[CapabilityNode] = Field(min_length=1)
    edges: list[GraphEdge] = Field(default_factory=list)
    max_total_steps: int = Field(default=100, ge=1, le=10_000)
    max_parallel_nodes: int = Field(default=4, ge=1, le=100)

    @model_validator(mode="after")
    def validate_references(self) -> CapabilityGraph:
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("capability node ids must be unique")
        known = set(ids)
        if self.entry_node_id not in known:
            raise ValueError("entry_node_id must reference a node")
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError("graph edge references an unknown node")
        return self

    @property
    def nodes_by_id(self) -> dict[str, CapabilityNode]:
        return {node.id: node for node in self.nodes}


class PlanCandidate(ContractModel):
    id: str = Field(default_factory=_id)
    goal_id: str
    graph_id: str
    provider: str = Field(min_length=1)
    placement: Placement
    risk_level: RiskLevel
    estimated_cost: float = Field(default=0, ge=0)
    estimated_duration_seconds: float | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0, le=1)
    fallback_plan_ids: list[str] = Field(default_factory=list)
    required_profile_id: str | None = None
    rationale: str = ""

    @model_validator(mode="after")
    def cannot_fallback_to_self(self) -> PlanCandidate:
        if self.id in self.fallback_plan_ids:
            raise ValueError("a plan cannot fall back to itself")
        return self


class PageState(ContractModel):
    id: str = Field(default_factory=_id)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    url: str = Field(min_length=1)
    title: str = ""
    dom_snapshot: str | None = None
    accessibility_snapshot: dict[str, Any] | list[Any] | None = None
    screenshot_artifact_id: str | None = None
    network_events: list[dict[str, Any]] = Field(default_factory=list)
    form_values: dict[str, Any] = Field(default_factory=dict)
    focused_element: str | None = None
    dialogs: list[dict[str, Any]] = Field(default_factory=list)
    browser_state: dict[str, Any] = Field(default_factory=dict)


class ActionKind(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    EXTRACT = "extract"
    EVALUATE = "evaluate"
    WAIT = "wait"
    HUMAN_TAKEOVER = "human_takeover"


class VerifierSpec(ContractModel):
    kind: str = Field(min_length=1)
    expectation: dict[str, Any]
    timeout_seconds: float = Field(default=10, gt=0, le=300)


class Action(ContractModel):
    id: str = Field(default_factory=_id)
    kind: ActionKind
    target: dict[str, Any] = Field(default_factory=dict)
    arguments: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[str] = Field(min_length=1)
    expected_effect: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel
    idempotency: IdempotencyClass
    verifier: VerifierSpec
    approval_id: str | None = None
    timeout_seconds: float = Field(default=30, gt=0, le=600)

    @model_validator(mode="after")
    def high_risk_requires_approval(self) -> Action:
        if self.risk_level.rank >= RiskLevel.L3.rank and not self.approval_id:
            raise ValueError("approval_id is required for L3-L4 actions")
        return self

    @property
    def requires_approval(self) -> bool:
        return self.risk_level.rank >= RiskLevel.L2.rank


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    NOT_RUN = "not_run"


class VerificationResult(ContractModel):
    status: VerificationStatus
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    observed: dict[str, Any] = Field(default_factory=dict)


class ActionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ErrorCategory(str, Enum):
    GROUNDING = "grounding"
    PAGE_CHANGED = "page_changed"
    AUTH_REQUIRED = "auth_required"
    PERMISSION_DENIED = "permission_denied"
    POLICY_BLOCKED = "policy_blocked"
    APPROVAL_REQUIRED = "approval_required"
    NETWORK = "network"
    BROWSER_CRASHED = "browser_crashed"
    NODE_OFFLINE = "node_offline"
    BUSINESS_REJECTED = "business_rejected"
    UNCERTAIN_COMMIT = "uncertain_commit"
    VALIDATION = "validation"
    INTERNAL = "internal"


class ActionResult(ContractModel):
    action_id: str
    status: ActionStatus
    verification: VerificationResult
    started_at: datetime | None = None
    finished_at: datetime | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    error_category: ErrorCategory | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def status_matches_verification(self) -> ActionResult:
        if (
            self.status == ActionStatus.SUCCEEDED
            and self.verification.status != VerificationStatus.PASSED
        ):
            raise ValueError("a succeeded action requires passed verification")
        if (
            self.status == ActionStatus.AMBIGUOUS
            and self.error_category != ErrorCategory.UNCERTAIN_COMMIT
        ):
            raise ValueError("ambiguous results must use uncertain_commit")
        return self

    @property
    def succeeded(self) -> bool:
        return (
            self.status == ActionStatus.SUCCEEDED
            and self.verification.status == VerificationStatus.PASSED
        )


class AgentEventKind(str, Enum):
    PLAN_CREATED = "plan_created"
    PLAN_SELECTED = "plan_selected"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    ACTION_REQUESTED = "action_requested"
    ACTION_COMPLETED = "action_completed"
    VERIFICATION_COMPLETED = "verification_completed"
    RECOVERY_STARTED = "recovery_started"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    TAKEOVER_REQUESTED = "takeover_requested"
    TAKEOVER_ENDED = "takeover_ended"


class AgentEvent(ContractModel):
    id: str = Field(default_factory=_id)
    run_id: str
    sequence: int = Field(ge=1)
    kind: AgentEventKind
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)


class RunState(str, Enum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_HUMAN = "waiting_human"
    WAITING_NODE = "waiting_node"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    AMBIGUOUS = "ambiguous"


class Run(ContractModel):
    id: str = Field(default_factory=_id)
    goal_id: str
    plan_id: str
    profile_id: str | None = None
    placement: Placement | None = None
    state: RunState = RunState.CREATED
    fencing_token: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunStep(ContractModel):
    id: str = Field(default_factory=_id)
    run_id: str
    node_id: str
    sequence: int = Field(ge=1)
    state: StepState = StepState.PENDING
    attempt_count: int = Field(default=0, ge=0)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class Approval(ContractModel):
    id: str = Field(default_factory=_id)
    run_id: str
    step_id: str | None = None
    action_hash: str = Field(min_length=1)
    profile_id: str
    placement: Placement
    risk_level: RiskLevel
    preview: dict[str, Any]
    diff: dict[str, Any]
    page_revision: str = Field(default="legacy:unbound", min_length=1)
    evidence_digest: str = Field(default="legacy:unbound", min_length=1)
    object_digest: str = Field(default="legacy:unbound", min_length=1)
    state: ApprovalState = ApprovalState.PENDING
    expires_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str | None = None

    @model_validator(mode="after")
    def expiry_is_timezone_aware(self) -> Approval:
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        return self

    def is_valid_for(
        self,
        *,
        action_hash: str,
        profile_id: str,
        placement: Placement,
        page_revision: str,
        evidence_digest: str,
        object_digest: str,
        now: datetime,
    ) -> bool:
        if now.tzinfo is None:
            raise ValueError("now must include a timezone")
        return (
            self.state == ApprovalState.APPROVED
            and now < self.expires_at
            and self.action_hash == action_hash
            and self.profile_id == profile_id
            and self.placement == placement
            and self.page_revision == page_revision
            and self.evidence_digest == evidence_digest
            and self.object_digest == object_digest
        )
