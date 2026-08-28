"""Graph execution, recovery, commit protection and replay tests."""

import pytest

from webauto.agent.execution import GraphExecutor, StepOutcome
from webauto.agent.model_provider import FallbackModelProvider, ModelRequest, ModelResponse
from webauto.agent.recovery import (
    CommitGuard,
    CommitState,
    FallbackChain,
    RecoveryExhausted,
    RecoveryStage,
)
from webauto.agent.replay import EventReplay
from webauto.domain import (
    AgentEventKind,
    CapabilityGraph,
    CapabilityNode,
    GraphEdge,
    IdempotencyClass,
)


@pytest.mark.asyncio
async def test_graph_executor_runs_steps_and_emits_auditable_events() -> None:
    graph = CapabilityGraph(
        id="graph-1",
        entry_node_id="observe",
        nodes=[
            CapabilityNode(id="observe", capability="web.observe"),
            CapabilityNode(id="extract", capability="web.extract"),
        ],
        edges=[GraphEdge(source="observe", target="extract")],
        max_total_steps=5,
    )
    calls = []

    async def observe(node, context):
        calls.append(node.id)
        return StepOutcome(output={"observed": True})

    async def extract(node, context):
        calls.append(node.id)
        return StepOutcome(output={"items": [1, 2]})

    result = await GraphExecutor({"web.observe": observe, "web.extract": extract}).run(
        run_id="run-1", graph=graph, context={}
    )

    assert result.succeeded
    assert calls == ["observe", "extract"]
    assert [event.sequence for event in result.events] == list(range(1, len(result.events) + 1))
    assert AgentEventKind.STEP_STARTED in [event.kind for event in result.events]


@pytest.mark.asyncio
async def test_graph_executor_stops_at_approval_node() -> None:
    graph = CapabilityGraph(
        entry_node_id="submit",
        nodes=[CapabilityNode(id="submit", capability="web.submit", approval_required=True)],
    )

    async def must_not_run(node, context):
        raise AssertionError("approval node executed without approval")

    result = await GraphExecutor({"web.submit": must_not_run}).run(
        run_id="run-1", graph=graph, context={}
    )
    assert not result.succeeded
    assert result.waiting_for_approval
    assert result.events[-1].kind == AgentEventKind.APPROVAL_REQUESTED


def test_fallback_chain_has_budget_and_never_skips_to_unbounded_retry() -> None:
    chain = FallbackChain(max_recoveries=3)
    assert chain.next().stage == RecoveryStage.REGROUNDED
    assert chain.next().stage == RecoveryStage.SITE_SKILL
    assert chain.next().stage == RecoveryStage.GENERAL_AGENT
    with pytest.raises(RecoveryExhausted):
        chain.next()


def test_non_idempotent_unknown_commit_requires_query_and_reapproval() -> None:
    guard = CommitGuard(IdempotencyClass.NON_IDEMPOTENT, approval_id="approval-1")
    guard.begin_submit()
    guard.mark_transport_unknown()
    assert guard.state == CommitState.VERIFYING_COMMIT
    with pytest.raises(RuntimeError, match="query"):
        guard.begin_submit()

    guard.record_query(found=False)
    assert guard.state == CommitState.REAPPROVAL_REQUIRED
    with pytest.raises(RuntimeError, match="approval"):
        guard.begin_submit()

    guard.reapprove("approval-2")
    guard.begin_submit()
    guard.confirm()
    assert guard.state == CommitState.CONFIRMED


class FakeModel:
    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.fail = fail

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if self.fail:
            raise TimeoutError(self.name)
        return ModelResponse(provider=self.name, content={"answer": "ok"}, cost=0.01)


@pytest.mark.asyncio
async def test_model_provider_fallback_is_auditable() -> None:
    provider = FallbackModelProvider([FakeModel("fast", fail=True), FakeModel("strong")])
    response = await provider.complete(ModelRequest(task="plan", payload={}))
    assert response.provider == "strong"
    assert provider.attempts == (("fast", "timeout"), ("strong", "success"))


def test_event_replay_rejects_sequence_gaps() -> None:
    replay = EventReplay()
    graph = CapabilityGraph(
        entry_node_id="one", nodes=[CapabilityNode(id="one", capability="web.observe")]
    )

    # Generate genuine events, then remove one to prove deterministic gap detection.
    import asyncio

    async def observe(node, context):
        return StepOutcome()

    result = asyncio.run(GraphExecutor({"web.observe": observe}).run("run-1", graph, {}))
    with pytest.raises(ValueError, match="sequence"):
        replay.replay(result.events[1:])


@pytest.mark.asyncio
async def test_forged_context_cannot_bypass_approval() -> None:
    graph = CapabilityGraph(
        entry_node_id="submit",
        nodes=[CapabilityNode(id="submit", capability="web.submit", approval_required=True)],
    )

    async def submit(node, context):
        return StepOutcome(output={"submitted": True})

    result = await GraphExecutor({"web.submit": submit}).run(
        run_id="run-1",
        graph=graph,
        context={"approved_node_ids": {"submit"}, "approval_id": "forged"},
    )
    assert result.waiting_for_approval


@pytest.mark.asyncio
async def test_verified_approval_allows_graph_node() -> None:
    graph = CapabilityGraph(
        entry_node_id="submit",
        nodes=[CapabilityNode(id="submit", capability="web.submit", approval_required=True)],
    )

    async def submit(node, context):
        return StepOutcome(output={"submitted": True})

    async def approval_checker(run_id, node, context):
        return run_id == "run-1" and context["approval_id"] == "approval-real"

    result = await GraphExecutor({"web.submit": submit}, approval_checker=approval_checker).run(
        "run-1", graph, {"approval_id": "approval-real"}
    )
    assert result.succeeded
