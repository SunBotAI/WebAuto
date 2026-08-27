"""Scenario-neutral goal compilation, planning, scoring and routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from webauto.domain import (
    AutonomyPolicy,
    CapabilityGraph,
    CapabilityNode,
    CapabilityRegistry,
    GoalContract,
    GraphEdge,
    PlanCandidate,
    RiskBudget,
    RiskLevel,
)


@dataclass(frozen=True, slots=True)
class CompilationResult:
    goal: GoalContract | None
    clarifications: tuple[str, ...] = ()


class GoalCompiler:
    def compile(
        self,
        objective: str,
        *,
        success_criteria: list[str],
        constraints: dict[str, object] | None = None,
        output_schema: dict[str, object] | None = None,
        autonomy_policy: AutonomyPolicy | None = None,
        risk_budget: RiskBudget | None = None,
    ) -> CompilationResult:
        objective = objective.strip()
        clarifications: list[str] = []
        if not objective or objective in {"帮我弄一下", "帮我处理", "处理一下", "搞一下"}:
            clarifications.append("请说明要操作的对象和期望结果")
        if not success_criteria:
            clarifications.append("请说明什么可验证状态代表任务完成")
        if clarifications:
            return CompilationResult(goal=None, clarifications=tuple(clarifications))
        return CompilationResult(
            goal=GoalContract(
                objective=objective,
                constraints=dict(constraints or {}),
                success_criteria=success_criteria,
                output_schema=dict(output_schema or {"type": "object"}),
                autonomy_policy=autonomy_policy or AutonomyPolicy(),
                risk_budget=risk_budget or RiskBudget(),
            )
        )


class RuleBasedCapabilityPlanner:
    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def plan(self, goal: GoalContract, capability_names: list[str]) -> CapabilityGraph:
        if not capability_names:
            raise ValueError("at least one capability is required")
        nodes: list[CapabilityNode] = []
        edges: list[GraphEdge] = []
        for index, name in enumerate(capability_names, start=1):
            capability = self._registry.get(name, "1.0.0")
            node_id = f"step-{index}"
            nodes.append(
                CapabilityNode(
                    id=node_id,
                    capability=name,
                    capability_version=capability.version,
                    approval_required=capability.risk_level.rank >= RiskLevel.L2.rank,
                    max_attempts=(1 if capability.idempotency.value == "non_idempotent" else 3),
                )
            )
            if index > 1:
                edges.append(GraphEdge(source=f"step-{index - 1}", target=node_id))
        return CapabilityGraph(
            entry_node_id="step-1",
            nodes=nodes,
            edges=edges,
            max_total_steps=max(10, len(nodes) * 3),
        )


@dataclass(frozen=True, slots=True)
class CandidateScore:
    candidate: PlanCandidate
    eligible: bool
    value: float
    reason: str


class CandidateScorer:
    _provider_weight: ClassVar[dict[str, float]] = {
        "site_skill": 0.15,
        "history": 0.10,
        "general_agent": 0.03,
        "human": 0.0,
    }

    def score(self, goal: GoalContract, candidate: PlanCandidate) -> CandidateScore:
        if candidate.goal_id != goal.id:
            return CandidateScore(candidate, False, float("-inf"), "goal mismatch")
        if candidate.risk_level.rank > goal.risk_budget.max_risk.rank:
            return CandidateScore(candidate, False, float("-inf"), "risk exceeds goal budget")
        placement_bonus = 0.05 if goal.preferred_placement == candidate.placement else 0.0
        value = (
            candidate.confidence * 0.75
            + self._provider_weight.get(candidate.provider, 0.0)
            + placement_bonus
            - min(candidate.estimated_cost, 100.0) * 0.01
            - candidate.risk_level.rank * 0.02
        )
        return CandidateScore(candidate, True, value, "eligible after hard constraints")


@dataclass(frozen=True, slots=True)
class RouteDecision:
    primary: PlanCandidate
    fallbacks: tuple[PlanCandidate, ...]
    scores: tuple[CandidateScore, ...]
    reason: str


class PlanRouter:
    def __init__(self, scorer: CandidateScorer) -> None:
        self._scorer = scorer

    def route(self, goal: GoalContract, candidates: list[PlanCandidate]) -> RouteDecision:
        scores = tuple(self._scorer.score(goal, candidate) for candidate in candidates)
        eligible = sorted(
            (score for score in scores if score.eligible),
            key=lambda score: score.value,
            reverse=True,
        )
        if not eligible:
            reasons = "; ".join(score.reason for score in scores)
            raise ValueError(f"no eligible plan candidate: {reasons}")
        return RouteDecision(
            primary=eligible[0].candidate,
            fallbacks=tuple(score.candidate for score in eligible[1:]),
            scores=scores,
            reason=f"selected {eligible[0].candidate.id} with score {eligible[0].value:.3f}; hard constraints applied first",
        )
