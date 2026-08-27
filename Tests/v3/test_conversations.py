"""Durable multi-turn Butler conversation and run-result tests."""

from __future__ import annotations

import pytest

from webauto.application import Actor, ApplicationService, Role
from webauto.application.service import PermissionDenied
from webauto.application.state import InMemoryApplicationStateStore
from webauto.domain import ConversationRole


def operator(tenant: str = "local") -> Actor:
    return Actor("local-user", tenant, {Role.OPERATOR})


@pytest.mark.asyncio
async def test_conversation_round_trip_context_and_tenant_isolation() -> None:
    state = InMemoryApplicationStateStore()
    first = ApplicationService(state_store=state)
    actor = operator()
    conversation = await first.create_conversation(actor, title="  比较 商品  ")
    conversation = await first.append_conversation_message(
        actor,
        conversation.id,
        role=ConversationRole.USER,
        content="比较两个页面里的商品",
    )
    conversation = await first.update_conversation_context(
        actor,
        conversation.id,
        last_intent="shopping",
        context={"urls": ["https://example.test/a"]},
    )
    conversation = await first.append_conversation_message(
        actor,
        conversation.id,
        role=ConversationRole.ASSISTANT,
        content="已经完成第一轮比较。",
        kind="completed",
    )

    restarted = ApplicationService(state_store=state)
    restored = await restarted.get_conversation(actor, conversation.id)
    assert restored.title == "比较 商品"
    assert [item.role for item in restored.messages] == [
        ConversationRole.USER,
        ConversationRole.ASSISTANT,
    ]
    assert restored.last_intent == "shopping"
    assert restored.context["urls"] == ["https://example.test/a"]
    assert (await restarted.list_conversations(actor))[0].id == conversation.id

    with pytest.raises(PermissionDenied):
        await restarted.get_conversation(operator("other"), conversation.id)


@pytest.mark.asyncio
async def test_run_list_result_and_terminal_timestamp_are_durable() -> None:
    state = InMemoryApplicationStateStore()
    service = ApplicationService(state_store=state)
    actor = operator()
    goal = await service.create_goal(
        actor,
        objective="read the authorized page",
        success_criteria=["result verified"],
    )
    run = await service.create_run(actor, goal_id=goal.id, plan_id="plan-1")
    await service.start_run(actor, run.id)
    await service.set_run_result(actor, run.id, {"summary": "verified"})
    finished = await service.finish_run(actor, run.id, succeeded=True)

    assert finished.finished_at is not None
    assert (await service.list_runs(actor))[0].id == run.id
    assert await service.get_run_result(actor, run.id) == {"summary": "verified"}
    assert (await service.run_detail(actor, run.id))["result"] == {"summary": "verified"}

    restarted = ApplicationService(state_store=state)
    assert await restarted.get_run_result(actor, run.id) == {"summary": "verified"}
