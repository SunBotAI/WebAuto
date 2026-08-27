"""Personal butler routing and real execution-backend handoff tests."""

import pytest

from webauto.application import Actor, ApplicationService, Role
from webauto.application.butler_service import (
    ButlerExecutionRequest,
    ButlerExecutionResult,
    ButlerIntent,
    ButlerService,
    IntentRouter,
)
from webauto.domain import RunState


class RecordingBackend:
    def __init__(self, result: ButlerExecutionResult) -> None:
        self.result = result
        self.requests: list[ButlerExecutionRequest] = []

    async def execute(self, request: ButlerExecutionRequest) -> ButlerExecutionResult:
        self.requests.append(request)
        return self.result


ACTOR = Actor("owner", "personal", {Role.OPERATOR, Role.APPROVER})


def test_intent_router_preserves_general_fallback_and_extracts_constraints() -> None:
    router = IntentRouter()
    assert router.classify("去咸鱼发布这个闲置") == ButlerIntent.XIANYU_PUBLISH
    assert router.classify("看看咸鱼有没有便宜的显示器") == ButlerIntent.XIANYU_BUY
    assert router.classify("查看咸鱼店铺的新消息") == ButlerIntent.XIANYU_MANAGE
    assert router.classify("比较淘宝和京东价格") == ButlerIntent.SHOPPING
    assert router.classify("打开 https://example.com 看一下") == ButlerIntent.WEB
    context = router.context("预算 3000 以内，只看 https://example.com 不要买")
    assert context == {"urls": ["https://example.com"], "budget": 3000.0, "read_only": True}


@pytest.mark.asyncio
async def test_butler_submits_execution_and_persists_successful_run() -> None:
    application = ApplicationService()
    backend = RecordingBackend(
        ButlerExecutionResult("succeeded", {"items": [{"title": "candidate"}]})
    )
    reply = await ButlerService(application, backend).handle(
        ACTOR, "比较淘宝和京东的显示器，预算 3000 以内，不要买"
    )
    assert reply.kind == "completed"
    assert backend.requests[0].intent == ButlerIntent.SHOPPING
    assert backend.requests[0].context["read_only"] is True
    run = await application.get_run(ACTOR, reply.payload["run_id"])
    assert run.state == RunState.SUCCEEDED
    assert [entry.action for entry in application.audit_log if entry.resource_id == run.id][
        -5:
    ] == ["run.create", "run.plan_view", "run.start", "run.result", "run.succeed"]


@pytest.mark.asyncio
async def test_butler_waits_for_approval_instead_of_claiming_completion() -> None:
    application = ApplicationService()
    backend = RecordingBackend(
        ButlerExecutionResult("waiting_approval", {"preview": {"price": 88}})
    )
    reply = await ButlerService(application, backend).handle(ACTOR, "发布一条咸鱼商品")
    assert reply.kind == "approval_required"
    run = await application.get_run(ACTOR, reply.payload["run_id"])
    assert run.state == RunState.WAITING_APPROVAL


@pytest.mark.asyncio
async def test_butler_failure_is_not_reported_as_success() -> None:
    application = ApplicationService()
    backend = RecordingBackend(ButlerExecutionResult("failed", error="browser offline"))
    reply = await ButlerService(application, backend).handle(
        ACTOR, "打开 https://example.com 看一下"
    )
    assert reply.kind == "failed"
    run = await application.get_run(ACTOR, reply.payload["run_id"])
    assert run.state == RunState.FAILED


@pytest.mark.asyncio
async def test_butler_clarifies_before_creating_any_run() -> None:
    application = ApplicationService()
    backend = RecordingBackend(ButlerExecutionResult("succeeded"))
    reply = await ButlerService(application, backend).handle(ACTOR, "帮我弄一下")
    assert reply.kind == "clarification"
    assert backend.requests == []


@pytest.mark.asyncio
async def test_butler_moves_run_to_human_takeover_on_browser_challenge() -> None:
    application = ApplicationService()
    backend = RecordingBackend(ButlerExecutionResult("waiting_human", {"challenge": "captcha"}))
    reply = await ButlerService(application, backend).handle(
        ACTOR, "打开 https://example.com 看一下"
    )
    assert reply.kind == "human_takeover"
    assert reply.payload["challenge"] == "captcha"
    run = await application.get_run(ACTOR, reply.payload["run_id"])
    assert run.state == RunState.WAITING_HUMAN
