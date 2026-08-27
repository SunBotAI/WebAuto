"""Deterministic AgentEvent replay and audit summary."""

from __future__ import annotations

from dataclasses import dataclass

from webauto.domain import AgentEvent, AgentEventKind


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    run_id: str
    last_sequence: int
    completed_steps: tuple[str, ...]
    awaiting_approval: bool


class EventReplay:
    def replay(self, events: tuple[AgentEvent, ...] | list[AgentEvent]) -> ReplaySummary:
        if not events:
            raise ValueError("cannot replay an empty event stream")
        run_id = events[0].run_id
        completed: list[str] = []
        awaiting_approval = False
        for expected, event in enumerate(events, start=1):
            if event.sequence != expected:
                raise ValueError(f"event sequence gap at {expected}")
            if event.run_id != run_id:
                raise ValueError("event stream contains multiple runs")
            if event.kind == AgentEventKind.STEP_COMPLETED and event.payload.get("succeeded"):
                completed.append(str(event.payload["node_id"]))
            if event.kind == AgentEventKind.APPROVAL_REQUESTED:
                awaiting_approval = True
            if event.kind == AgentEventKind.APPROVAL_RESOLVED:
                awaiting_approval = False
        return ReplaySummary(run_id, events[-1].sequence, tuple(completed), awaiting_approval)
