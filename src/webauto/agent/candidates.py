"""Generate auditable plan candidates from skills, general agents and humans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from webauto.domain import GoalContract, Placement, PlanCandidate, RiskLevel


class CandidateSource(str, Enum):
    SITE_SKILL = "site_skill"
    HISTORY = "history"
    GENERAL_AGENT = "general_agent"
    HUMAN = "human"


@dataclass(frozen=True, slots=True)
class GeneratedCandidate:
    source: CandidateSource
    plan: PlanCandidate


class CandidateGenerator:
    def generate(
        self,
        *,
        goal: GoalContract,
        graph_id: str,
        placements: list[Placement],
        site_skill_available: bool,
        historical_success_rate: float | None = None,
    ) -> tuple[GeneratedCandidate, ...]:
        if not placements:
            raise ValueError("at least one allowed placement is required")
        generated: list[GeneratedCandidate] = []
        primary_placement = goal.preferred_placement or placements[0]
        if primary_placement not in placements:
            raise ValueError("preferred placement is not allowed")
        if site_skill_available:
            generated.append(
                GeneratedCandidate(
                    CandidateSource.SITE_SKILL,
                    PlanCandidate(
                        goal_id=goal.id,
                        graph_id=graph_id,
                        provider="site_skill",
                        placement=primary_placement,
                        risk_level=goal.risk_budget.max_risk,
                        confidence=max(0.5, min(historical_success_rate or 0.8, 0.99)),
                        rationale="versioned site skill candidate",
                    ),
                )
            )
        for placement in placements:
            generated.append(
                GeneratedCandidate(
                    CandidateSource.GENERAL_AGENT,
                    PlanCandidate(
                        goal_id=goal.id,
                        graph_id=graph_id,
                        provider="general_agent",
                        placement=placement,
                        risk_level=goal.risk_budget.max_risk,
                        confidence=0.6,
                        estimated_cost=0.2,
                        rationale="general browser agent fallback",
                    ),
                )
            )
        generated.append(
            GeneratedCandidate(
                CandidateSource.HUMAN,
                PlanCandidate(
                    goal_id=goal.id,
                    graph_id=graph_id,
                    provider="human",
                    placement=primary_placement,
                    risk_level=RiskLevel.L0,
                    confidence=0.99,
                    rationale="authorized human takeover fallback",
                ),
            )
        )
        return tuple(generated)
