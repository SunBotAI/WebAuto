"""MCP coverage for shopping/Xianyu workspaces and governed actions."""

from __future__ import annotations

import base64

import pytest

from webauto.application import Actor, ApplicationService, Role
from webauto.application.mcp import call_tool, list_tools
from webauto.application.settings import RuntimeConfigStore
from webauto.domain import ApprovalState, Placement


async def mcp_source_run(service: ApplicationService, actor: Actor) -> str:
    goal = await service.create_goal(
        actor, objective="collect product", success_criteria=["collected"]
    )
    run = await service.create_run(
        actor,
        goal_id=goal.id,
        plan_id="source",
        placement=Placement.DESKTOP_MANAGED,
        profile_id="personal",
    )
    await service.start_run(actor, run.id)
    return run.id


@pytest.mark.asyncio
async def test_mcp_builds_vertical_workspace_and_preserves_unconsumed_approval(
    tmp_path,
) -> None:
    service = ApplicationService()
    store = RuntimeConfigStore(tmp_path / "var")
    token = store.mcp_authorizer.token()
    actor = Actor("mcp-local", "local", {Role.ADMIN})
    run_id = await mcp_source_run(service, actor)

    shopping = await call_tool(
        "shopping_workspace_create",
        {
            "mcp_token": token,
            "source_run_id": run_id,
            "message": "比较鼠标预算200",
            "candidates": [
                {
                    "platform": "jd",
                    "item_id": "mouse-1",
                    "title": "无线鼠标",
                    "url": "https://item.jd.com/mouse-1.html",
                    "price": "129",
                    "in_stock": True,
                }
            ],
        },
        service=service,
        settings_store=store,
    )
    assert shopping["success"] is True
    workspace_id = shopping["data"]["id"]
    prepared = await call_tool(
        "governed_action_prepare",
        {
            "mcp_token": token,
            "category": "shopping",
            "workspace_id": workspace_id,
            "operation": "add_to_cart",
            "object_scope": {"candidate_key": "jd:mouse-1"},
            "preview": {
                "title": "无线鼠标",
                "total": "129",
                "button_text": "加入购物车",
            },
            "page_revision": "page-1",
            "evidence_ids": ["shot-1"],
            "source_url": "https://item.jd.com/mouse-1.html",
            "allowed_domains": ["item.jd.com"],
        },
        service=service,
        settings_store=store,
    )
    assert prepared["success"] is True
    approval_id = prepared["data"]["approval_id"]
    await service.approve(actor, approval_id)
    execution = await call_tool(
        "governed_action_execute",
        {"mcp_token": token, "preview_id": prepared["data"]["id"]},
        service=service,
        settings_store=store,
    )
    assert execution["success"] is False
    assert "remains unconsumed" in execution["error"]
    assert (await service.list_approvals(actor))[-1].state == ApprovalState.APPROVED


@pytest.mark.asyncio
async def test_mcp_file_upload_authorize_and_xianyu_listing(tmp_path) -> None:
    service = ApplicationService()
    store = RuntimeConfigStore(tmp_path / "var")
    token = store.mcp_authorizer.token()
    actor = Actor("mcp-local", "local", {Role.ADMIN})
    run_id = await mcp_source_run(service, actor)
    uploaded = await call_tool(
        "file_upload",
        {
            "mcp_token": token,
            "filename": "item.png",
            "media_type": "image/png",
            "content_base64": base64.b64encode(b"\x89PNG\r\n\x1a\nitem-image").decode(),
        },
        service=service,
        settings_store=store,
    )
    file_id = uploaded["data"]["id"]
    authorized = await call_tool(
        "file_authorize",
        {"mcp_token": token, "file_id": file_id, "run_id": run_id},
        service=service,
        settings_store=store,
    )
    assert authorized["success"] is True
    listing = await call_tool(
        "xianyu_listing_workspace_create",
        {
            "mcp_token": token,
            "source_run_id": run_id,
            "draft": {
                "title": "闲置键盘",
                "description": "自用闲置，瑕疵已经如实说明",
                "price": "99",
                "category": "电脑配件",
                "condition": "八成新",
            },
            "file_ids": [file_id],
        },
        service=service,
        settings_store=store,
    )
    assert listing["success"] is True
    assert listing["data"]["draft"]["images"][0]["file_id"] == file_id

    names = {definition["name"] for definition in list_tools()}
    assert {
        "file_upload",
        "shopping_workspace_create",
        "xianyu_listing_workspace_create",
        "governed_action_prepare",
        "governed_action_execute",
    } <= names
