"""Control API and Butler chat integration tests."""

import pytest

from webauto.application import Actor, ApplicationService, Role
from webauto.application.butler import ButlerChat
from webauto.application.butler_service import ButlerExecutionResult, ButlerService
from webauto.application.control_api import create_app

HEADERS = {
    "x-user-id": "user-1",
    "x-tenant-id": "tenant-1",
    "x-roles": "operator",
}


@pytest.mark.asyncio
async def test_control_api_uses_application_service_for_run_lifecycle() -> None:
    httpx = pytest.importorskip("httpx")
    service = ApplicationService()
    app = create_app(service, allow_trusted_headers=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        goal_response = await client.post(
            "/v1/goals",
            headers=HEADERS,
            json={"objective": "查看授权页面商品", "success_criteria": ["结果已验证"]},
        )
        assert goal_response.status_code == 201
        goal_id = goal_response.json()["id"]
        run_response = await client.post(
            "/v1/runs", headers=HEADERS, json={"goal_id": goal_id, "plan_id": "plan-1"}
        )
        run_id = run_response.json()["id"]
        started = await client.post(f"/v1/runs/{run_id}/start", headers=HEADERS)
        assert started.json()["state"] == "running"
        paused = await client.post(f"/v1/runs/{run_id}/pause", headers=HEADERS)
        assert paused.json()["state"] == "paused"
        plans = await client.put(
            f"/v1/runs/{run_id}/plans",
            headers=HEADERS,
            json={
                "candidates": [{"id": "plan-1", "score": 0.9}],
                "selection_reason": "verified skill candidate",
            },
        )
        assert plans.status_code == 200
        plan_view = await client.get(f"/v1/runs/{run_id}/plans", headers=HEADERS)
        assert plan_view.json()["selection_reason"] == "verified skill candidate"
        profile = await client.put(
            "/v1/profiles",
            headers=HEADERS,
            json={"id": "profile-1", "value": {"login_health": "ok"}},
        )
        assert profile.status_code == 200
        assert (await client.get("/v1/profiles", headers=HEADERS)).json()["profile-1"]
        detail = await client.get(f"/v1/runs/{run_id}", headers=HEADERS)
        assert detail.json()["goal_id"] == goal_id
    assert [item.action for item in service.audit_log[-3:]] == [
        "run.pause",
        "run.plan_view",
        "profiles.upsert",
    ]


@pytest.mark.asyncio
async def test_control_api_requires_authentication_context() -> None:
    httpx = pytest.importorskip("httpx")
    app = create_app(ApplicationService(), allow_trusted_headers=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/goals", json={"objective": "查看授权页面商品", "success_criteria": ["已验证"]}
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_butler_chat_clarifies_then_creates_goal() -> None:
    service = ApplicationService()
    chat = ButlerChat(service)
    operator = Actor("user-1", "tenant-1", {Role.OPERATOR})
    clarification = await chat.handle(operator, "帮我弄一下")
    assert clarification.kind == "clarification"
    created = await chat.handle(
        operator,
        "查看授权页面商品",
        success_criteria=["结果已验证"],
    )
    assert created.kind == "goal_created"
    assert created.payload["goal_id"]


class _SuccessfulBackend:
    async def execute(self, request):
        return ButlerExecutionResult(status="succeeded", output={"url": request.context["urls"][0]})


@pytest.mark.asyncio
async def test_control_api_butler_endpoint_uses_injected_execution_backend() -> None:
    httpx = pytest.importorskip("httpx")
    service = ApplicationService()
    app = create_app(
        service,
        butler=ButlerService(service, _SuccessfulBackend()),
        allow_trusted_headers=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/butler/messages",
            headers=HEADERS,
            json={"message": "打开 https://example.test 看看商品"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "completed"
    assert body["payload"]["result"]["url"] == "https://example.test"
