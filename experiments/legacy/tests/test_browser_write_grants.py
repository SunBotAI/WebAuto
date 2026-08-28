"""Unforgeable one-write browser grants and payment boundaries."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from webauto.agent_backends import (
    BrowserAgentPolicyViolation,
    BrowserAgentSecurityPolicy,
    BrowserWriteGrantAuthority,
)
from webauto.domain import AgentTaskBudget, AgentTaskRequest, Placement, RiskLevel
from webauto.runtime.reliability import approval_binding_digest


def request_for(
    grant: dict,
    approved_object: dict,
    files: tuple[Path, ...] = (),
) -> AgentTaskRequest:
    return AgentTaskRequest(
        run_id="run-1",
        objective="approved add to cart",
        success_criteria=("cart contains item",),
        profile_id="personal",
        placement=Placement.DESKTOP_MANAGED,
        allowed_domains=("item.example.com",),
        available_files=files,
        context={
            "approved_external_write": grant,
            "approved_object": approved_object,
        },
        read_only=False,
        max_risk=RiskLevel.L3,
        budget=AgentTaskBudget(max_external_writes=1),
    )


def test_write_grant_rejects_forgery_reuse_and_changed_files(tmp_path: Path) -> None:
    authority = BrowserWriteGrantAuthority(b"x" * 32)
    image = tmp_path / "item.jpg"
    image.write_bytes(b"approved-image")
    approved_object = {
        "source_url": "https://item.example.com/publish",
        "final_control": "确认发布",
    }
    grant = authority.issue(
        run_id="run-1",
        operation="xianyu_publish",
        object_digest=approval_binding_digest(approved_object),
        source_url="https://item.example.com/publish",
        files=(image,),
    )
    request = request_for(grant.model_dump(mode="json"), approved_object, (image,))
    assert authority.validate_request(request).id == grant.id

    forged = grant.model_dump(mode="json")
    forged["operation"] = "place_order"
    with pytest.raises(PermissionError, match="issued|signature"):
        authority.validate_request(request_for(forged, approved_object, (image,)))

    image.write_bytes(b"changed-image")
    with pytest.raises(PermissionError, match="checksum"):
        authority.validate_request(request)


class FakeAction:
    def __init__(self, function, description="action") -> None:
        self.function = function
        self.description = description

    def model_copy(self, *, update):
        return FakeAction(update["function"], update["description"])


class FakeTools:
    def __init__(self, click) -> None:
        actions = {
            "navigate": FakeAction(lambda **_: None),
            "click": FakeAction(click),
        }
        self.registry = SimpleNamespace(registry=SimpleNamespace(actions=actions))


class FakeNode:
    tag_name = "button"

    def __init__(self, text: str) -> None:
        self.attributes = {"type": "button"}
        self._text = text

    def get_meaningful_text_for_llm(self) -> str:
        return self._text


class FakeBrowserSession:
    def __init__(self, text: str, url: str) -> None:
        self.node = FakeNode(text)
        self.url = url

    async def get_element_by_index(self, index: int):
        assert index == 1
        return self.node

    async def get_current_page_url(self) -> str:
        return self.url


@pytest.mark.asyncio
async def test_final_click_consumes_exact_operation_once_and_payment_is_human() -> None:
    calls: list[str] = []

    async def click(**_):
        calls.append("clicked")
        return "ok"

    authority = BrowserWriteGrantAuthority(b"y" * 32)
    policy = BrowserAgentSecurityPolicy(authority)
    cart_object = {
        "source_url": "https://item.example.com/item-1",
        "final_control": "加入购物车",
    }
    grant = authority.issue(
        run_id="run-1",
        operation="add_to_cart",
        object_digest=approval_binding_digest(cart_object),
        source_url="https://item.example.com/item-1",
    )
    request = request_for(grant.model_dump(mode="json"), cart_object)
    tools = policy.protect_tools(FakeTools(click), request)
    guarded = tools.registry.registry.actions["click"].function
    params = SimpleNamespace(index=1)
    with pytest.raises(BrowserAgentPolicyViolation, match="final control differs"):
        await guarded(
            params=params,
            browser_session=FakeBrowserSession("提交订单", "https://item.example.com/item-1"),
        )
    with pytest.raises(BrowserAgentPolicyViolation, match="page URL differs"):
        await guarded(
            params=params,
            browser_session=FakeBrowserSession("加入购物车", "https://item.example.com/item-2"),
        )
    assert (
        await guarded(
            params=params,
            browser_session=FakeBrowserSession("加入购物车", "https://item.example.com/item-1"),
        )
        == "ok"
    )
    assert calls == ["clicked"]
    with pytest.raises(BrowserAgentPolicyViolation, match="already consumed"):
        await guarded(
            params=params,
            browser_session=FakeBrowserSession("加入购物车", "https://item.example.com/item-1"),
        )

    payment_object = {
        "source_url": "https://item.example.com/checkout",
        "final_control": "确认支付",
    }
    payment_grant = authority.issue(
        run_id="run-1",
        operation="place_order",
        object_digest=approval_binding_digest(payment_object),
        source_url="https://item.example.com/checkout",
    )
    payment_request = request_for(payment_grant.model_dump(mode="json"), payment_object)
    payment_tools = policy.protect_tools(FakeTools(click), payment_request)
    with pytest.raises(BrowserAgentPolicyViolation, match="payment always requires human"):
        await payment_tools.registry.registry.actions["click"].function(
            params=params,
            browser_session=FakeBrowserSession("确认支付", "https://item.example.com/checkout"),
        )
