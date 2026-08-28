"""Scenario-neutral planning, scoring, routing and verification tests."""

import pytest

from webauto.agent import (
    CandidateScorer,
    GoalCompiler,
    PlanRouter,
    RuleBasedCapabilityPlanner,
    StateVerifier,
)
from webauto.domain import (
    CapabilityDefinition,
    CapabilityRegistry,
    IdempotencyClass,
    PageState,
    Placement,
    PlanCandidate,
    RiskBudget,
    RiskLevel,
    VerificationStatus,
    VerifierSpec,
)


def registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        [
            CapabilityDefinition(
                name="web.observe",
                version="1.0.0",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                preconditions=["authorized_page"],
                risk_level=RiskLevel.L0,
                idempotency=IdempotencyClass.READ_ONLY,
            ),
            CapabilityDefinition(
                name="web.form.submit",
                version="1.0.0",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                preconditions=["approved_preview"],
                risk_level=RiskLevel.L3,
                idempotency=IdempotencyClass.NON_IDEMPOTENT,
            ),
        ]
    )


@pytest.mark.parametrize(
    "objective",
    ["搜索预算内商品", "发布已确认的闲置物品", "预约下周服务"],
)
def test_goal_compiler_uses_same_contract_for_three_scenarios(objective: str) -> None:
    result = GoalCompiler().compile(
        objective,
        success_criteria=["页面和业务状态均已验证"],
        risk_budget=RiskBudget(max_risk=RiskLevel.L3),
    )
    assert result.goal.objective == objective
    assert not result.clarifications
    assert "scenario" not in type(result.goal).model_fields


def test_goal_compiler_requests_clarification_instead_of_inventing_goal() -> None:
    result = GoalCompiler().compile("帮我弄一下", success_criteria=[])
    assert result.clarifications
    assert result.goal is None


def test_rule_planner_builds_bounded_graph_from_registered_capabilities() -> None:
    goal = (
        GoalCompiler()
        .compile(
            "提交已审批表单",
            success_criteria=["提交结果已查询"],
            risk_budget=RiskBudget(max_risk=RiskLevel.L3),
        )
        .goal
    )
    graph = RuleBasedCapabilityPlanner(registry()).plan(goal, ["web.observe", "web.form.submit"])
    assert graph.entry_node_id == "step-1"
    assert graph.nodes_by_id["step-2"].approval_required
    assert graph.max_total_steps >= len(graph.nodes)


def test_scorer_applies_risk_hard_constraint_before_weighted_score() -> None:
    scorer = CandidateScorer()
    goal = (
        GoalCompiler()
        .compile(
            "只读查看",
            success_criteria=["结果已验证"],
            risk_budget=RiskBudget(max_risk=RiskLevel.L1),
        )
        .goal
    )
    safe = PlanCandidate(
        goal_id=goal.id,
        graph_id="g1",
        provider="site_skill",
        placement=Placement.DESKTOP_MANAGED,
        risk_level=RiskLevel.L1,
        confidence=0.7,
        estimated_cost=0.2,
    )
    risky = PlanCandidate(
        goal_id=goal.id,
        graph_id="g2",
        provider="general_agent",
        placement=Placement.DESKTOP_MANAGED,
        risk_level=RiskLevel.L3,
        confidence=0.99,
        estimated_cost=0.0,
    )
    assert scorer.score(goal, safe).eligible
    rejected = scorer.score(goal, risky)
    assert not rejected.eligible
    assert "risk" in rejected.reason


def test_router_selects_primary_and_auditable_fallbacks() -> None:
    goal = GoalCompiler().compile("查看页面", success_criteria=["已验证"]).goal
    candidates = [
        PlanCandidate(
            id="plan-general",
            goal_id=goal.id,
            graph_id="g2",
            provider="general_agent",
            placement=Placement.BROWSER_ATTACH,
            risk_level=RiskLevel.L1,
            confidence=0.6,
        ),
        PlanCandidate(
            id="plan-skill",
            goal_id=goal.id,
            graph_id="g1",
            provider="site_skill",
            placement=Placement.DESKTOP_MANAGED,
            risk_level=RiskLevel.L1,
            confidence=0.9,
        ),
    ]
    decision = PlanRouter(CandidateScorer()).route(goal, candidates)
    assert decision.primary.id == "plan-skill"
    assert [item.id for item in decision.fallbacks] == ["plan-general"]
    assert decision.reason


@pytest.mark.asyncio
async def test_state_verifier_never_reports_success_without_matching_evidence() -> None:
    verifier = StateVerifier()
    state = PageState(
        url="https://example.test/result",
        dom_snapshot="<main>尚未完成</main>",
        form_values={"status": "pending"},
    )
    result = await verifier.verify(
        VerifierSpec(
            kind="page_state",
            expectation={"url_contains": "/result", "dom_contains": "发布成功"},
        ),
        state,
    )
    assert result.status == VerificationStatus.FAILED
    assert result.evidence_ids == []
