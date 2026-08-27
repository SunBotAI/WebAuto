"""HTTP contract for multi-turn conversations and persisted run history."""

from __future__ import annotations

import pytest

from webauto.application import ApplicationService
from webauto.application.butler_service import ButlerExecutionResult, ButlerService
from webauto.application.control_api import create_app

HEADERS = {
    "x-user-id": "owner",
    "x-tenant-id": "personal",
    "x-roles": "operator,approver",
}


class ApiBackend:
    async def execute(self, request):
        return ButlerExecutionResult(
            "succeeded", {"message": request.message, "context": request.context}
        )


@pytest.mark.asyncio
async def test_http_continues_conversation_and_exposes_timeline_and_result() -> None:
    httpx = pytest.importorskip("httpx")
    service = ApplicationService()
    app = create_app(
        service,
        butler=ButlerService(service, ApiBackend()),
        allow_trusted_headers=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/v1/butler/messages",
            headers=HEADERS,
            json={"message": ("比较 https://example.test/products 的商品，预算 800，不要买")},
        )
        conversation_id = first.json()["payload"]["conversation_id"]
        second = await client.post(
            "/v1/butler/messages",
            headers=HEADERS,
            json={
                "conversation_id": conversation_id,
                "message": "只看支持七天退货的",
            },
        )
        run_id = second.json()["payload"]["run_id"]
        conversations = await client.get("/v1/conversations", headers=HEADERS)
        conversation = await client.get(f"/v1/conversations/{conversation_id}", headers=HEADERS)
        runs = await client.get("/v1/runs?states=succeeded&limit=10", headers=HEADERS)
        detail = await client.get(f"/v1/runs/{run_id}/detail", headers=HEADERS)
        result = await client.get(f"/v1/runs/{run_id}/result", headers=HEADERS)

    assert first.status_code == second.status_code == 200
    assert conversations.status_code == conversation.status_code == 200
    assert len(conversation.json()["messages"]) == 4
    assert conversation.json()["context"]["budget"] == 800.0
    assert any(item["id"] == run_id for item in runs.json())
    assert detail.json()["result"]["status"] == "succeeded"
    assert any(item["action"] == "run.result" for item in detail.json()["timeline"])
    assert result.json()["output"]["context"]["budget"] == 800.0


@pytest.mark.asyncio
async def test_http_conversation_is_tenant_scoped() -> None:
    httpx = pytest.importorskip("httpx")
    service = ApplicationService()
    app = create_app(
        service,
        butler=ButlerService(service, ApiBackend()),
        allow_trusted_headers=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/butler/messages",
            headers=HEADERS,
            json={"message": "打开 https://example.test 查看"},
        )
        conversation_id = created.json()["payload"]["conversation_id"]
        denied = await client.get(
            f"/v1/conversations/{conversation_id}",
            headers={
                "x-user-id": "other",
                "x-tenant-id": "other",
                "x-roles": "operator",
            },
        )

    assert denied.status_code == 403
