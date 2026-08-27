"""Convert successful general-Agent traces into review-only Skill candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .sandbox import SkillSandbox
from .sdk import LoadedSkill, SkillLoader


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    skill: LoadedSkill
    trace_id: str
    fixture_pass_rate: float
    requires_review: bool
    created_at: datetime


class SkillCandidateBuilder:
    def __init__(self) -> None:
        self._sandbox = SkillSandbox()
        self._loader = SkillLoader()

    def build(
        self,
        *,
        manifest_payload: dict,
        trace_id: str,
        fixture_results: list[bool],
    ) -> SkillCandidate:
        if not trace_id:
            raise ValueError("trace_id is required")
        if not fixture_results:
            raise ValueError("at least one fixture replay result is required")
        self._sandbox.validate_payload(manifest_payload)
        skill = self._loader.load_dict(manifest_payload)
        pass_rate = sum(fixture_results) / len(fixture_results)
        return SkillCandidate(
            skill=skill,
            trace_id=trace_id,
            fixture_pass_rate=pass_rate,
            requires_review=True,
            created_at=datetime.now(timezone.utc),
        )
