"""MCP contract for multi-turn Butler tasks, history and runtime control."""

from __future__ import annotations

import pytest

from webauto.application import ApplicationService
from webauto.application.butler_service import ButlerExecutionResult, ButlerService
from webauto.application.mcp import call_tool, list_tools
from webauto.application.settings import RuntimeConfigStore


class McpBackend:
    def __init__(self) -> None:
        self.controls: list[tuple[str, str]] = []

    async def execute(self, request):
        return ButlerExecutionResult("succeeded", {"message": request.message})

    async def pause(self, run_id: str) -> None:
        self.controls.append(("pause", run_id))

    async def resume(self, run_id: str, user_input: str | None = None) -> None:
        self.controls.append(("resume", run_id))

    async def cancel(self, run_id: str) -> None:
        self.controls.append(("cancel", run_id))


@pytest.mark.asyncio
async def test_mcp_can_continue_conversation_and_read_run_history(tmp_path) -> None:
    service = ApplicationService()
    store = RuntimeConfigStore(tmp_path / "var")
    token = store.mcp_authorizer.token()
    butler = ButlerService(service, McpBackend())

    first = await call_tool(
        "butler_message",
        {
            "mcp_token": token,
            "message": "比较 https://example.test/products 的商品，预算 500，不要买",
        },
        service=service,
        butler=butler,
        settings_store=store,
    )
    conversation_id = first["data"]["payload"]["conversation_id"]
    continued = await call_tool(
        "task_continue",
        {
            "mcp_token": token,
            "conversation_id": conversation_id,
            "message": "只保留有保修的",
        },
        service=service,
        butler=butler,
        settings_store=store,
    )
    run_id = continued["data"]["payload"]["run_id"]

    conversations = await call_tool(
        "conversation_list",
        {"mcp_token": token},
        service=service,
        settings_store=store,
    )
    runs = await call_tool(
        "run_list",
        {"mcp_token": token},
        service=service,
        settings_store=store,
    )
    detail = await call_tool(
        "run_detail",
        {"mcp_token": token, "run_id": run_id},
        service=service,
        settings_store=store,
    )
    result = await call_tool(
        "run_result",
        {"mcp_token": token, "run_id": run_id},
        service=service,
        settings_store=store,
    )

    assert conversations["success"] is True
    assert conversations["data"][0]["id"] == conversation_id
    assert len(conversations["data"][0]["messages"]) == 4
    assert any(item["id"] == run_id for item in runs["data"])
    assert detail["data"]["result"]["status"] == "succeeded"
    assert result["data"]["output"]["message"] == "只保留有保修的"


@pytest.mark.asyncio
async def test_mcp_run_controls_reach_butler_backend(tmp_path) -> None:
    service = ApplicationService()
    store = RuntimeConfigStore(tmp_path / "var")
    token = store.mcp_authorizer.token()
    backend = McpBackend()
    butler = ButlerService(service, backend)

    goal = await call_tool(
        "goal_create",
        {
            "mcp_token": token,
            "objective": "读取授权页面",
            "success_criteria": ["结果已验证"],
        },
        service=service,
        settings_store=store,
    )
    run = await call_tool(
        "run_create",
        {
            "mcp_token": token,
            "goal_id": goal["data"]["id"],
            "plan_id": "plan-1",
        },
        service=service,
        settings_store=store,
    )
    run_id = run["data"]["id"]
    await call_tool(
        "run_start",
        {"mcp_token": token, "run_id": run_id},
        service=service,
        settings_store=store,
    )
    paused = await call_tool(
        "run_pause",
        {"mcp_token": token, "run_id": run_id},
        service=service,
        butler=butler,
        settings_store=store,
    )

    assert paused["data"]["state"] == "paused"
    assert backend.controls == [("pause", run_id)]
    names = {item["name"] for item in list_tools()}
    assert {
        "task_continue",
        "conversation_list",
        "conversation_get",
        "run_list",
        "run_detail",
        "run_result",
    } <= names
