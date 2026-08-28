"""Control-API coverage for shopping and Xianyu governed workspaces."""

from __future__ import annotations

import base64

import pytest

from webauto.application import Actor, ApplicationService, Role
from webauto.application.control_api import create_app
from webauto.domain import ApprovalState

HEADERS = {
    "x-user-id": "local-user",
    "x-tenant-id": "local",
    "x-roles": "admin",
}


async def create_source_run(client) -> str:
    goal = await client.post(
        "/v1/goals",
        headers=HEADERS,
        json={"objective": "collect product", "success_criteria": ["collected"]},
    )
    run = await client.post(
        "/v1/runs",
        headers=HEADERS,
        json={
            "goal_id": goal.json()["id"],
            "plan_id": "source",
            "placement": "desktop_managed",
            "profile_id": "personal",
        },
    )
    run_id = run.json()["id"]
    await client.post(f"/v1/runs/{run_id}/start", headers=HEADERS)
    return run_id


@pytest.mark.asyncio
async def test_shopping_action_preview_does_not_consume_when_dynamic_writer_is_off(
    tmp_path,
) -> None:
    httpx = pytest.importorskip("httpx")
    service = ApplicationService()
    app = create_app(service, allow_trusted_headers=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        run_id = await create_source_run(client)
        created = await client.post(
            "/v1/shopping/workspaces",
            headers=HEADERS,
            json={
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
        )
        assert created.status_code == 201
        workspace = created.json()
        prepared = await client.post(
            f"/v1/vertical/workspaces/shopping/{workspace['id']}/actions",
            headers=HEADERS,
            json={
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
        )
        assert prepared.status_code == 201
        action = prepared.json()
        assert action["object_scope"]["item_id"] == "mouse-1"
        approved = await client.post(
            f"/v1/approvals/{action['approval_id']}/approve", headers=HEADERS
        )
        assert approved.status_code == 200
        execution = await client.post(
            f"/v1/governed-actions/{action['id']}/execute", headers=HEADERS
        )
        assert execution.status_code == 409
        assert "remains unconsumed" in execution.json()["detail"]

    approvals = await service.list_approvals(Actor("local-user", "local", {Role.ADMIN}))
    assert approvals[-1].state == ApprovalState.APPROVED


@pytest.mark.asyncio
async def test_xianyu_publish_accepts_only_source_run_granted_images(tmp_path) -> None:
    httpx = pytest.importorskip("httpx")
    app = create_app(ApplicationService(), allow_trusted_headers=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        run_id = await create_source_run(client)
        uploaded = await client.post(
            "/v1/files",
            headers=HEADERS,
            json={
                "filename": "keyboard.png",
                "media_type": "image/png",
                "content_base64": base64.b64encode(b"\x89PNG\r\n\x1a\nlisting-image").decode(),
            },
        )
        file_id = uploaded.json()["id"]
        await client.post(f"/v1/runs/{run_id}/files/{file_id}/authorize", headers=HEADERS)
        listing_response = await client.post(
            "/v1/xianyu/listings",
            headers=HEADERS,
            json={
                "source_run_id": run_id,
                "draft": {
                    "title": "闲置机械键盘",
                    "description": "自用闲置，所有瑕疵已如实说明",
                    "price": "199",
                    "category": "电脑配件",
                    "condition": "九成新",
                },
                "file_ids": [file_id],
            },
        )
        assert listing_response.status_code == 201
        listing = listing_response.json()
        prepared = await client.post(
            f"/v1/vertical/workspaces/xianyu_listing/{listing['id']}/actions",
            headers=HEADERS,
            json={
                "operation": "xianyu_publish",
                "object_scope": {},
                "preview": {
                    "title": "闲置机械键盘",
                    "price": "199",
                    "button_text": "确认发布",
                },
                "page_revision": "publish-page-1",
                "evidence_ids": ["publish-shot-1"],
                "source_url": "https://www.goofish.com/publish",
                "allowed_domains": ["www.goofish.com"],
                "file_ids": [file_id],
            },
        )
        assert prepared.status_code == 201
        body = prepared.json()
        assert body["available_files"][0]["file_id"] == file_id
        assert body["object_scope"]["files"][0]["sha256"]
