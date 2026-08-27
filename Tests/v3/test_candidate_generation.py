"""Candidate generation contract tests."""

from webauto.agent.candidates import CandidateGenerator, CandidateSource
from webauto.agent.planning import GoalCompiler
from webauto.domain import Placement, RiskBudget, RiskLevel


def test_generator_produces_primary_fallback_and_human_candidates() -> None:
    goal = (
        GoalCompiler()
        .compile(
            "完成授权网页任务",
            success_criteria=["状态已验证"],
            risk_budget=RiskBudget(max_risk=RiskLevel.L3),
        )
        .goal
    )
    candidates = CandidateGenerator().generate(
        goal=goal,
        graph_id="graph-1",
        placements=[Placement.DESKTOP_MANAGED, Placement.BROWSER_ATTACH],
        site_skill_available=True,
        historical_success_rate=0.82,
    )
    sources = {item.source for item in candidates}
    assert {
        CandidateSource.SITE_SKILL,
        CandidateSource.GENERAL_AGENT,
        CandidateSource.HUMAN,
    } <= sources
    assert len({item.plan.id for item in candidates}) == len(candidates)
