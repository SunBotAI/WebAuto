"""Chat-to-browser approval binding acceptance tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from webauto.agent_backends import (
    BrowserAgentPolicyViolation,
    BrowserAgentSecurityPolicy,
    BrowserUseAdapter,
)
from webauto.application import Actor, ApplicationService, Role
from webauto.application.browser_agent import BrowserAgentCoordinator
from webauto.application.butler_service import (
    ButlerExecutionRequest,
    ButlerExecutionResult,
    ButlerService,
)
from webauto.domain import AgentTaskRequest, AgentTaskStatus, Placement, RunState


class _Action:
    def __init__(self, function, description: str = "") -> None:
        self.function = function
        self.description = description

    def model_copy(self, *, update):
        return _Action(update.get("function", self.function), update.get("description", ""))


class _Node:
    tag_name = "button"
    node_value = ""
    ax_node = None

    def __init__(self) -> None:
        self.attributes = {"type": "button"}

    def get_meaningful_text_for_llm(self) -> str:
        return "加入购物车"


class _Session:
    async def get_element_by_index(self, index: int):
        assert index == 1
        return _Node()

    async def get_current_page_url(self) -> str:
        return (
            "https://item.example.test/item?id=tb-1&token=secret&sid=private"
            "&auth=credential&keep=visible#fragment"
        )


@pytest.mark.asyncio
async def test_final_tool_boundary_returns_sanitized_structured_approval_request() -> None:
    async def navigate(**_):
        return "ok"

    async def click(**_):
        raise AssertionError("the unapproved external write must never reach the site")

    tools = SimpleNamespace(
        registry=SimpleNamespace(
            registry=SimpleNamespace(
                actions={"navigate": _Action(navigate), "click": _Action(click)}
            )
        )
    )
    request = AgentTaskRequest(
        run_id="read-run",
        objective="add the selected product to cart",
        success_criteria=("approval preview returned",),
        profile_id="personal",
        placement=Placement.DESKTOP_MANAGED,
        allowed_domains=("item.example.test",),
    )
    guarded = BrowserAgentSecurityPolicy().protect_tools(tools, request)
    with pytest.raises(BrowserAgentPolicyViolation) as raised:
        await guarded.registry.registry.actions["click"].function(
            params=SimpleNamespace(index=1), browser_session=_Session()
        )

    result = BrowserUseAdapter(
        model_factory=lambda: object(), controlled_tools=object()
    )._policy_result(raised.value)
    approval = result.output["approval_request"]

    assert result.status == AgentTaskStatus.WAITING_APPROVAL
    assert approval["operation"] == "add_to_cart"
    assert approval["button_text"] == "加入购物车"
    assert approval["current_url"] == ("https://item.example.test/item?id=tb-1&keep=visible")
    assert approval["page_revision"]
    assert approval["evidence_ids"] == [approval["current_url"]]
    assert "secret" not in str(result.model_dump(mode="json"))
    assert "credential" not in str(result.model_dump(mode="json"))


class _SequenceBackend:
    def __init__(self, results: list[ButlerExecutionResult]) -> None:
        self.results = list(results)
        self.requests: list[ButlerExecutionRequest] = []

    async def execute(self, request: ButlerExecutionRequest) -> ButlerExecutionResult:
        self.requests.append(request)
        return self.results.pop(0)


def _product_result() -> ButlerExecutionResult:
    return ButlerExecutionResult(
        "succeeded",
        {
            "agent_result": {
                "output": {
                    "entities": [
                        {
                            "kind": "product",
                            "platform": "taobao",
                            "id": "tb-1",
                            "title": "机械键盘 A",
                            "url": "https://item.taobao.com/item.htm?id=tb-1",
                            "fields": {
                                "price": "399",
                                "shipping": "0",
                                "in_stock": True,
                                "seller_score": 0.95,
                            },
                            "evidence_urls": ["https://item.taobao.com/item.htm?id=tb-1"],
                        }
                    ]
                },
                "uncertainties": [],
            }
        },
    )


def _approval_result(item_id: str = "tb-1") -> ButlerExecutionResult:
    current_url = f"https://item.taobao.com/item.htm?id={item_id}&spm=search"
    return ButlerExecutionResult(
        "waiting_approval",
        {
            "agent_result": {
                "output": {
                    "approval_request": {
                        "operation": "add_to_cart",
                        "button_text": "加入购物车",
                        "target": {
                            "tag": "button",
                            "text": "加入购物车",
                            "attributes": {"type": "button"},
                        },
                        "current_url": current_url,
                        "page_revision": "sha256:page-1",
                        "evidence_ids": [current_url],
                    }
                }
            }
        },
    )


@pytest.mark.asyncio
async def test_chat_remembers_candidate_and_creates_exact_low_risk_approval() -> None:
    actor = Actor("owner", "personal", {Role.ADMIN})
    application = ApplicationService()
    backend = _SequenceBackend([_product_result(), _approval_result()])
    butler = ButlerService(application, backend)

    first = await butler.handle(actor, "比较淘宝机械键盘，预算500，只看不要买")
    conversation_id = first.payload["conversation_id"]
    conversation = await application.get_conversation(actor, conversation_id)
    workspace_id = conversation.context["shopping_workspace_id"]
    assert conversation.context["selected_candidate_key"] == "taobao:tb-1"

    second = await butler.handle(
        actor,
        "把推荐的加入购物车，1件",
        conversation_id=conversation_id,
    )

    assert second.kind == "approval_required"
    assert second.payload["approval_id"]
    governed = second.payload["governed_action"]
    assert governed["workspace_id"] == workspace_id
    assert governed["object_scope"]["item_id"] == "tb-1"
    assert governed["object_scope"]["final_control"] == "加入购物车"
    assert governed["object_scope"]["source_url"].endswith("id=tb-1&spm=search")
    assert (await application.get_run(actor, second.payload["read_run_id"])).state == (
        RunState.SUCCEEDED
    )
    assert (await application.get_run(actor, second.payload["run_id"])).state == (
        RunState.WAITING_APPROVAL
    )
    approvals = await application.list_approvals(actor)
    assert [item.id for item in approvals] == [second.payload["approval_id"]]


@pytest.mark.asyncio
async def test_chat_refuses_to_bind_a_different_product_page() -> None:
    actor = Actor("owner", "personal", {Role.ADMIN})
    application = ApplicationService()
    backend = _SequenceBackend([_product_result(), _approval_result("tb-2")])
    butler = ButlerService(application, backend)

    first = await butler.handle(actor, "比较淘宝机械键盘，预算500，只看不要买")
    second = await butler.handle(
        actor,
        "把推荐的加入购物车",
        conversation_id=first.payload["conversation_id"],
    )

    assert second.kind == "approval_required"
    assert "approval_id" not in second.payload
    assert (await application.get_run(actor, second.payload["run_id"])).state == (
        RunState.WAITING_APPROVAL
    )
    assert not await application.list_approvals(actor)


def test_only_low_risk_shopping_operations_enable_approval_probe() -> None:
    assert BrowserAgentCoordinator._approval_probe_operation("加入购物车") == "add_to_cart"
    assert BrowserAgentCoordinator._approval_probe_operation("去结算看看") == "start_checkout"
    assert BrowserAgentCoordinator._approval_probe_operation("提交订单") is None
    assert BrowserAgentCoordinator._approval_probe_operation("确认支付") is None
