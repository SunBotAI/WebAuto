"""Deterministic PageState grounding before optional visual-model fallback."""

from __future__ import annotations

from dataclasses import dataclass

from webauto.domain import PageState


@dataclass(frozen=True, slots=True)
class GroundingTarget:
    name: str
    role: str | None = None
    landmark: str | None = None


@dataclass(frozen=True, slots=True)
class LocatorCandidate:
    selector: str
    strategy: str
    confidence: float
    evidence: str


class PageStateGrounder:
    def __init__(self, *, landmarks: dict[str, str] | None = None) -> None:
        self._landmarks = dict(landmarks or {})

    def ground(self, target: GroundingTarget, state: PageState) -> list[LocatorCandidate]:
        candidates: list[LocatorCandidate] = []
        if target.landmark and target.landmark in self._landmarks:
            candidates.append(
                LocatorCandidate(
                    self._landmarks[target.landmark], "landmark", 0.98, target.landmark
                )
            )
        accessibility = str(state.accessibility_snapshot or "")
        if target.name in accessibility and target.role:
            candidates.append(
                LocatorCandidate(
                    f"role={target.role},name={target.name}",
                    "accessibility",
                    0.88,
                    target.name,
                )
            )
        if target.name in (state.dom_snapshot or ""):
            candidates.append(
                LocatorCandidate(f"text={target.name}", "dom_text", 0.70, target.name)
            )
        return sorted(candidates, key=lambda item: item.confidence, reverse=True)
