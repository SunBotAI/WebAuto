"""Shopping and Xianyu vertical workflow acceptance tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from webauto.application import Actor, ApplicationService, Role
from webauto.application.vertical_workflows import (
    SHOPPING_WORKSPACES,
    XIANYU_BUY_WORKSPACES,
    XIANYU_LISTING_WORKSPACES,
    XIANYU_STORE_WORKSPACES,
    VerticalWorkflowService,
)
from webauto.domain import Action, ApprovalState, Placement, RunState


@pytest.fixture
def actor() -> Actor:
    return Actor("local-user", "local", {Role.ADMIN})


async def source_run(application: ApplicationService, actor: Actor):
    goal = await application.create_goal(
        actor,
        objective="collect vertical facts",
        success_criteria=["facts collected"],
    )
    run = await application.create_run(
        actor,
        goal_id=goal.id,
        plan_id="source-plan",
        placement=Placement.DESKTOP_MANAGED,
        profile_id="personal",
    )
    return await application.start_run(actor, run.id)


@pytest.mark.asyncio
async def test_shopping_result_card_and_bound_cart_action_are_tenant_durable(
    actor: Actor,
) -> None:
    application = ApplicationService()
    run = await source_run(application, actor)
    workflows = VerticalWorkflowService(application)

    workspace = await workflows.create_shopping_workspace(
        actor,
        source_run_id=run.id,
        message="帮我比较机械键盘，预算500，只看不要买",
        candidates=[
            {
                "platform": "taobao",
                "item_id": "tb-1",
                "title": "机械键盘 A",
                "url": "https://item.taobao.com/item.htm?id=tb-1",
                "price": "399",
                "shipping": "0",
                "in_stock": True,
                "seller_score": 0.9,
                "evidence_urls": ["https://item.taobao.com/item.htm?id=tb-1"],
            },
            {
                "platform": "jd",
                "item_id": "jd-1",
                "title": "机械键盘 B",
                "url": "https://item.jd.com/jd-1.html",
                "price": "459",
                "shipping": "0",
                "in_stock": True,
                "seller_score": 0.95,
            },
        ],
    )

    assert workspace["request"]["budget"] == "500"
    assert workspace["result_card"]["eligible_count"] == 2
    assert workspace["result_card"]["recommended_key"] == "taobao:tb-1"
    stored = await workflows.get_workspace(actor, SHOPPING_WORKSPACES, workspace["id"])
    assert stored == workspace

    preview = await workflows.prepare_action(
        actor,
        workspace_category=SHOPPING_WORKSPACES,
        workspace_id=workspace["id"],
        operation="add_to_cart",
        object_scope={
            "candidate_key": "taobao:tb-1",
            "quantity": 1,
            "address_masked": "上海市***",
        },
        preview={
            "title": "机械键盘 A",
            "total": "399",
            "button_text": "加入购物车",
        },
        page_revision="sha256:page-1",
        evidence_ids=["https://item.taobao.com/item.htm?id=tb-1"],
        source_url="https://item.taobao.com/item.htm?id=tb-1",
        allowed_domains=["item.taobao.com"],
    )
    approvals = await application.list_approvals(actor)
    assert approvals[-1].state == ApprovalState.PENDING
    assert preview["object_scope"]["item_id"] == "tb-1"
    assert preview["object_scope"]["operation"] == "add_to_cart"
    assert preview["object_scope"]["allowed_domains"] == ["item.taobao.com"]
    assert (
        await application.get_run(actor, preview["action_run_id"])
    ).state == RunState.WAITING_APPROVAL

    await application.approve(actor, preview["approval_id"])
    consumed = await workflows.consume_action(actor, preview["id"])
    assert consumed["state"] == "approved_once"
    assert (await application.get_run(actor, preview["action_run_id"])).state == RunState.RUNNING
    action = Action.model_validate({**consumed["action"], "approval_id": consumed["approval_id"]})
    await application.claim_consumed_approval_execution(
        actor,
        consumed["approval_id"],
        action=action,
        operation="add_to_cart",
        object_scope=consumed["object_scope"],
    )
    with pytest.raises(RuntimeError, match="already claimed"):
        await application.claim_consumed_approval_execution(
            actor,
            consumed["approval_id"],
            action=action,
            operation="add_to_cart",
            object_scope=consumed["object_scope"],
        )


@pytest.mark.asyncio
async def test_payment_is_human_only_and_creates_no_automation_approval(
    actor: Actor,
) -> None:
    application = ApplicationService()
    run = await source_run(application, actor)
    workflows = VerticalWorkflowService(application)
    workspace = await workflows.create_shopping_workspace(
        actor,
        source_run_id=run.id,
        message="买耳机预算300",
        candidates=[
            {
                "platform": "jd",
                "item_id": "headset-1",
                "title": "耳机",
                "url": "https://item.jd.com/headset-1.html",
                "price": "199",
                "in_stock": True,
            }
        ],
    )
    handoff = await workflows.prepare_action(
        actor,
        workspace_category=SHOPPING_WORKSPACES,
        workspace_id=workspace["id"],
        operation="payment",
        object_scope={"candidate_key": "jd:headset-1"},
        preview={"amount": "199", "address_masked": "北京市***"},
        page_revision="checkout-1",
        evidence_ids=["checkout-screen"],
        source_url="https://trade.jd.com/shopping/order/getOrderInfo.action",
        allowed_domains=["trade.jd.com"],
    )
    assert handoff["state"] == "waiting_human"
    assert handoff["automation_allowed"] is False
    assert (
        await application.get_run(actor, handoff["action_run_id"])
    ).state == RunState.WAITING_HUMAN
    assert await application.list_approvals(actor) == ()


@pytest.mark.asyncio
async def test_xianyu_buy_listing_and_store_workspaces_keep_vertical_boundaries(
    actor: Actor,
    tmp_path: Path,
) -> None:
    application = ApplicationService()
    run = await source_run(application, actor)
    workflows = VerticalWorkflowService(application)
    buy = await workflows.create_xianyu_buy_workspace(
        actor,
        source_run_id=run.id,
        item={
            "id": "xy-1",
            "title": "二手相机",
            "url": "https://www.goofish.com/item?id=xy-1",
            "price": "500",
            "market_price": "2000",
            "description": "很新",
            "real_photos": False,
            "off_platform_contact": True,
        },
    )
    assert buy["risk_assessment"]["level"] == "high"
    inquiry = await workflows.prepare_action(
        actor,
        workspace_category=XIANYU_BUY_WORKSPACES,
        workspace_id=buy["id"],
        operation="xianyu_send_message",
        object_scope={},
        preview={
            "message": buy["inquiry_drafts"][0],
            "button_text": "发送",
        },
        page_revision="xy-page-1",
        evidence_ids=["xy-shot-1"],
        source_url="https://www.goofish.com/item?id=xy-1",
        allowed_domains=["www.goofish.com"],
    )
    assert inquiry["object_scope"]["message"] == buy["inquiry_drafts"][0]

    listing = await workflows.create_xianyu_listing_workspace(
        actor,
        source_run_id=run.id,
        draft={
            "title": "闲置机械键盘",
            "description": "自用闲置，瑕疵已如实说明",
            "price": "199",
            "category": "电脑配件",
            "condition": "九成新",
        },
        image_grants=[{"file_id": "file-1", "filename": "keyboard.jpg", "sha256": "a" * 64}],
    )
    publish = await workflows.prepare_action(
        actor,
        workspace_category=XIANYU_LISTING_WORKSPACES,
        workspace_id=listing["id"],
        operation="xianyu_publish",
        object_scope={"untrusted": "ignored"},
        preview={
            "title": listing["draft"]["title"],
            "price": "199",
            "button_text": "确认发布",
        },
        page_revision="publish-preview-1",
        evidence_ids=["publish-shot-1"],
        source_url="https://www.goofish.com/publish",
        available_files=[{"file_id": "file-1", "sha256": "a" * 64}],
        allowed_domains=["www.goofish.com"],
    )
    assert publish["object_scope"]["listing_digest"] == listing["digest"]
    assert publish["object_scope"]["image_sha256s"] == ["a" * 64]
    assert "untrusted" not in publish["object_scope"]

    store = await workflows.create_xianyu_store_workspace(
        actor,
        source_run_id=run.id,
        records=[
            {"kind": "item", "id": "listing-1", "status": "online"},
            {"kind": "message", "id": "message-1", "text": "还在吗"},
            {"kind": "order", "id": "order-1", "status": "pending"},
        ],
    )
    assert len(store["snapshot"]["items"]) == 1
    assert len(store["snapshot"]["messages"]) == 1
    assert len(store["snapshot"]["orders"]) == 1
    assert (await workflows.get_workspace(actor, XIANYU_STORE_WORKSPACES, store["id"])) == store
