"""Multi-turn Butler context, run results and runtime lifecycle tests."""

from __future__ import annotations

import pytest

from webauto.application import Actor, ApplicationService, Role
from webauto.application.butler_service import (
    ButlerExecutionRequest,
    ButlerExecutionResult,
    ButlerIntent,
    ButlerService,
)
from webauto.domain import Placement, RunState

ACTOR = Actor("owner", "personal", {Role.OPERATOR, Role.APPROVER})


class LifecycleBackend:
    def __init__(self) -> None:
        self.requests: list[ButlerExecutionRequest] = []
        self.controls: list[tuple[str, str, str | None]] = []

    async def execute(self, request: ButlerExecutionRequest) -> ButlerExecutionResult:
        self.requests.append(request)
        return ButlerExecutionResult("succeeded", {"summary": request.message})

    async def pause(self, run_id: str) -> None:
        self.controls.append(("pause", run_id, None))

    async def resume(self, run_id: str, user_input: str | None = None) -> None:
        self.controls.append(("resume", run_id, user_input))

    async def cancel(self, run_id: str) -> None:
        self.controls.append(("cancel", run_id, None))


@pytest.mark.asyncio
async def test_follow_up_inherits_conversation_scope_and_persists_results() -> None:
    application = ApplicationService()
    backend = LifecycleBackend()
    butler = ButlerService(application, backend)

    first = await butler.handle(
        ACTOR,
        "比较 https://example.test/products 的显示器，预算 3000 以内，不要买",
    )
    conversation_id = first.payload["conversation_id"]
    second = await butler.handle(
        ACTOR,
        "再便宜一点，优先保修",
        conversation_id=conversation_id,
    )

    request = backend.requests[-1]
    assert request.intent == ButlerIntent.SHOPPING
    assert request.context["urls"] == ["https://example.test/products"]
    assert request.context["budget"] == 3000.0
    assert request.context["read_only"] is True
    assert request.context["conversation_history"] == [
        {
            "role": "user",
            "content": ("比较 https://example.test/products 的显示器，预算 3000 以内，不要买"),
        }
    ]
    assert second.payload["conversation_id"] == conversation_id
    conversation = await application.get_conversation(ACTOR, conversation_id)
    assert len(conversation.messages) == 4
    assert conversation.last_intent == ButlerIntent.SHOPPING.value
    run_id = second.payload["run_id"]
    assert (await application.get_run(ACTOR, run_id)).state == RunState.SUCCEEDED
    assert (await application.get_run_result(ACTOR, run_id))["status"] == "succeeded"


@pytest.mark.asyncio
async def test_control_operations_reach_backend_before_state_transition() -> None:
    application = ApplicationService()
    backend = LifecycleBackend()
    butler = ButlerService(application, backend)
    goal = await application.create_goal(
        ACTOR, objective="操作授权页面", success_criteria=["状态已验证"]
    )
    run = await application.create_run(
        ACTOR,
        goal_id=goal.id,
        plan_id="plan-1",
        profile_id="personal",
        placement=Placement.DESKTOP_MANAGED,
    )
    await application.start_run(ACTOR, run.id)

    assert (await butler.pause(ACTOR, run.id)).state == RunState.PAUSED
    assert (await butler.resume(ACTOR, run.id, user_input="已处理登录")).state == RunState.RUNNING
    assert (await butler.takeover(ACTOR, run.id)).state == RunState.WAITING_HUMAN
    assert (await butler.return_control(ACTOR, run.id)).state == RunState.RUNNING
    assert (await butler.cancel(ACTOR, run.id)).state == RunState.CANCELLED
    assert backend.controls == [
        ("pause", run.id, None),
        ("resume", run.id, "已处理登录"),
        ("pause", run.id, None),
        ("resume", run.id, None),
        ("cancel", run.id, None),
    ]
