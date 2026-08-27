"""Bounded CapabilityGraph executor with an append-only event trail."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from webauto.domain import AgentEvent, AgentEventKind, CapabilityGraph, CapabilityNode


@dataclass(frozen=True, slots=True)
class StepOutcome:
    succeeded: bool = True
    output: dict[str, Any] = field(default_factory=dict)
    branch: str = "always"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class GraphRunResult:
    succeeded: bool
    outputs: dict[str, dict[str, Any]]
    events: tuple[AgentEvent, ...]
    waiting_for_approval: bool = False
    failed_node_id: str | None = None


StepHandler = Callable[[CapabilityNode, dict[str, Any]], Awaitable[StepOutcome]]
ApprovalChecker = Callable[[str, CapabilityNode, dict[str, Any]], Awaitable[bool]]


class GraphExecutor:
    def __init__(
        self,
        handlers: dict[str, StepHandler],
        *,
        approval_checker: ApprovalChecker | None = None,
    ) -> None:
        self._handlers = dict(handlers)
        self._approval_checker = approval_checker

    async def run(
        self,
        run_id: str,
        graph: CapabilityGraph,
        context: dict[str, Any],
    ) -> GraphRunResult:
        events: list[AgentEvent] = []
        outputs: dict[str, dict[str, Any]] = {}

        def emit(kind: AgentEventKind, payload: dict[str, Any]) -> None:
            events.append(
                AgentEvent(run_id=run_id, sequence=len(events) + 1, kind=kind, payload=payload)
            )

        current_id: str | None = graph.entry_node_id
        executed = 0
        while current_id is not None:
            executed += 1
            if executed > graph.max_total_steps:
                emit(AgentEventKind.RECOVERY_STARTED, {"reason": "graph step budget exhausted"})
                return GraphRunResult(False, outputs, tuple(events), failed_node_id=current_id)
            node = graph.nodes_by_id[current_id]
            emit(AgentEventKind.STEP_STARTED, {"node_id": node.id, "capability": node.capability})
            approval_valid = (not node.approval_required) or (
                self._approval_checker is not None
                and await self._approval_checker(run_id, node, context)
            )
            if not approval_valid:
                emit(AgentEventKind.APPROVAL_REQUESTED, {"node_id": node.id})
                return GraphRunResult(
                    False, outputs, tuple(events), waiting_for_approval=True, failed_node_id=node.id
                )
            handler = self._handlers.get(node.capability)
            if handler is None:
                raise KeyError(f"no handler for capability {node.capability}")
            outcome = await handler(node, context)
            outputs[node.id] = outcome.output
            emit(
                AgentEventKind.STEP_COMPLETED,
                {"node_id": node.id, "succeeded": outcome.succeeded, "error": outcome.error},
            )
            if not outcome.succeeded:
                return GraphRunResult(False, outputs, tuple(events), failed_node_id=node.id)
            edges = sorted(
                (
                    edge
                    for edge in graph.edges
                    if edge.source == node.id and edge.condition in {"always", outcome.branch}
                ),
                key=lambda edge: edge.priority,
                reverse=True,
            )
            current_id = edges[0].target if edges else None
        return GraphRunResult(True, outputs, tuple(events))
