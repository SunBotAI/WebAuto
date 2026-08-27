"""Contract tests for the scenario-neutral WebAuto v3 domain."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from webauto.domain import (
    Action,
    ActionKind,
    ActionResult,
    ActionStatus,
    AgentEvent,
    AgentEventKind,
    Approval,
    ApprovalState,
    AutonomyPolicy,
    BrowserFeature,
    CapabilityDefinition,
    CapabilityGraph,
    CapabilityNode,
    CapabilityRegistry,
    ErrorCategory,
    GoalContract,
    GraphEdge,
    IdempotencyClass,
    PageState,
    Placement,
    PlanCandidate,
    RiskBudget,
    RiskLevel,
    Run,
    RunState,
    RunStep,
    StepState,
    VerificationResult,
    VerificationStatus,
    VerifierSpec,
)


def make_goal(objective: str) -> GoalContract:
    return GoalContract(
        objective=objective,
        constraints={"authorized_accounts_only": True},
        success_criteria=["目标页面状态已经回读确认"],
        output_schema={"type": "object", "required": ["evidence"]},
        autonomy_policy=AutonomyPolicy(max_autonomous_risk=RiskLevel.L1),
        risk_budget=RiskBudget(max_risk=RiskLevel.L3, max_amount="500.00", currency="CNY"),
        deadline=datetime(2026, 8, 22, tzinfo=timezone.utc),
        preferred_placement=Placement.DESKTOP_MANAGED,
    )


@pytest.mark.parametrize(
    "objective",
    [
        "寻找符合预算的商品并加入购物车",
        "把已确认的二手商品草稿发布到授权店铺",
        "预约下周三可用的服务时段",
    ],
)
def test_goal_contract_is_scenario_neutral_and_round_trips(objective: str) -> None:
    goal = make_goal(objective)

    restored = GoalContract.model_validate_json(goal.model_dump_json())

    assert restored == goal
    assert "scenario" not in GoalContract.model_fields


def test_goal_requires_success_criteria() -> None:
    with pytest.raises(ValidationError):
        GoalContract(objective="打开网页", success_criteria=[])


def test_registry_rejects_duplicate_capability_versions() -> None:
    capability = CapabilityDefinition(
        name="web.form.submit",
        version="1.0.0",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        preconditions=["form_is_valid"],
        risk_level=RiskLevel.L3,
        idempotency=IdempotencyClass.NON_IDEMPOTENT,
        required_browser_features={BrowserFeature.DOM, BrowserFeature.SCREENSHOT},
    )
    registry = CapabilityRegistry()
    registry.register(capability)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(capability)


def test_capability_graph_validates_edges_and_loop_limits() -> None:
    graph = CapabilityGraph(
        entry_node_id="observe",
        nodes=[
            CapabilityNode(id="observe", capability="web.observe", max_attempts=2),
            CapabilityNode(id="approve", capability="human.approval", approval_required=True),
        ],
        edges=[GraphEdge(source="observe", target="approve", condition="candidate_found")],
        max_total_steps=10,
    )
    assert graph.nodes_by_id["approve"].approval_required

    with pytest.raises(ValidationError):
        CapabilityGraph(
            entry_node_id="missing",
            nodes=[CapabilityNode(id="observe", capability="web.observe")],
        )


def test_plan_candidate_carries_fallback_without_site_fields() -> None:
    plan = PlanCandidate(
        goal_id="goal-1",
        graph_id="graph-1",
        provider="playwright",
        placement=Placement.BROWSER_ATTACH,
        risk_level=RiskLevel.L2,
        estimated_cost=0.2,
        confidence=0.85,
        fallback_plan_ids=["plan-safe", "plan-human"],
    )
    assert plan.fallback_plan_ids == ["plan-safe", "plan-human"]
    assert "site" not in PlanCandidate.model_fields


def test_page_state_serializes_multimodal_observation() -> None:
    state = PageState(
        url="https://example.test/item/1",
        title="商品详情",
        dom_snapshot="<main>...</main>",
        accessibility_snapshot={"role": "main"},
        screenshot_artifact_id="artifact-1",
        network_events=[{"method": "GET", "status": 200}],
        form_values={"price": "99.00"},
        focused_element="button#submit",
        dialogs=[{"type": "confirm", "text": "确认？"}],
    )
    assert PageState.model_validate_json(state.model_dump_json()) == state


def test_every_action_requires_preconditions_and_verifier() -> None:
    action = Action(
        kind=ActionKind.CLICK,
        target={"role": "button", "name": "提交"},
        arguments={},
        preconditions=["preview_matches_approval"],
        risk_level=RiskLevel.L3,
        idempotency=IdempotencyClass.NON_IDEMPOTENT,
        verifier=VerifierSpec(kind="page_state", expectation={"published": True}),
        approval_id="approval-1",
    )
    assert action.requires_approval

    with pytest.raises(ValidationError):
        Action(
            kind=ActionKind.CLICK,
            target={"text": "提交"},
            preconditions=[],
            risk_level=RiskLevel.L3,
            idempotency=IdempotencyClass.NON_IDEMPOTENT,
            verifier=VerifierSpec(kind="page_state", expectation={"published": True}),
        )


def test_high_risk_action_requires_approval_reference() -> None:
    with pytest.raises(ValidationError, match="approval_id"):
        Action(
            kind=ActionKind.CLICK,
            target={"text": "支付"},
            preconditions=["amount_confirmed"],
            risk_level=RiskLevel.L4,
            idempotency=IdempotencyClass.NON_IDEMPOTENT,
            verifier=VerifierSpec(kind="business_query", expectation={"paid": True}),
        )


def test_ambiguous_result_cannot_claim_success() -> None:
    verification = VerificationResult(
        status=VerificationStatus.AMBIGUOUS,
        summary="提交响应超时，业务结果未知",
        evidence_ids=["trace-1"],
    )
    result = ActionResult(
        action_id="action-1",
        status=ActionStatus.AMBIGUOUS,
        verification=verification,
        error_category=ErrorCategory.UNCERTAIN_COMMIT,
    )
    assert not result.succeeded


def test_agent_event_round_trips() -> None:
    event = AgentEvent(
        run_id="run-1",
        sequence=1,
        kind=AgentEventKind.APPROVAL_REQUESTED,
        payload={"action_id": "action-1"},
    )
    assert AgentEvent.model_validate_json(event.model_dump_json()) == event


def test_approval_is_bound_to_action_profile_placement_and_expiry() -> None:
    approval = Approval(
        run_id="run-1",
        action_hash="sha256:abc",
        profile_id="profile-1",
        placement=Placement.DESKTOP_MANAGED,
        risk_level=RiskLevel.L3,
        preview={"title": "发布商品"},
        diff={"price": {"before": None, "after": "99.00"}},
        page_revision="page-rev-1",
        evidence_digest="sha256:evidence-1",
        object_digest="sha256:object-1",
        state=ApprovalState.APPROVED,
        expires_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)

    assert approval.is_valid_for(
        action_hash="sha256:abc",
        profile_id="profile-1",
        placement=Placement.DESKTOP_MANAGED,
        page_revision="page-rev-1",
        evidence_digest="sha256:evidence-1",
        object_digest="sha256:object-1",
        now=now,
    )
    assert not approval.is_valid_for(
        action_hash="sha256:abc",
        profile_id="profile-1",
        placement=Placement.BROWSER_ATTACH,
        page_revision="page-rev-1",
        evidence_digest="sha256:evidence-1",
        object_digest="sha256:object-1",
        now=now,
    )


def test_run_and_step_contracts_share_generic_states() -> None:
    run = Run(goal_id="goal-1", plan_id="plan-1", state=RunState.READY)
    step = RunStep(
        run_id=run.id,
        node_id="observe",
        sequence=1,
        state=StepState.PENDING,
    )
    assert step.run_id == run.id
    assert "scenario" not in Run.model_fields
