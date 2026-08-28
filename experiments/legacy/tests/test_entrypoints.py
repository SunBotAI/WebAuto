"""M6-10/CL-09 unified product-entry contract tests."""

import pytest

from webauto.application import ApplicationService
from webauto.application.butler_service import ButlerExecutionResult, ButlerService
from webauto.application.cli import execute
from webauto.application.control_api import create_app
from webauto.application.mcp import call_tool, list_tools
from webauto.application.settings import RuntimeConfigStore

CONTEXT = {"user_id": "operator-1", "tenant_id": "tenant-1", "roles": ["operator"]}


@pytest.mark.asyncio
async def test_cli_and_mcp_share_application_service_semantics(tmp_path) -> None:
    service = ApplicationService()
    store = RuntimeConfigStore(tmp_path / "var")
    mcp_token = store.mcp_authorizer.token()
    created = await execute(
        "create_goal",
        {
            **CONTEXT,
            "user_id": "mcp-local",
            "tenant_id": "local",
            "roles": ["admin"],
            "objective": "查看授权商品",
            "success_criteria": ["结果已验证"],
        },
        service=service,
    )
    assert created["success"] is True

    run = await call_tool(
        "run_create",
        {
            **CONTEXT,
            "mcp_token": mcp_token,
            "goal_id": created["data"]["id"],
            "plan_id": "plan-1",
        },
        service=service,
        settings_store=store,
    )
    assert run["success"] is True

    started = await call_tool(
        "run_start",
        {**CONTEXT, "mcp_token": mcp_token, "run_id": run["data"]["id"]},
        service=service,
        settings_store=store,
    )
    assert started["data"]["state"] == "running"
    assert [item.action for item in service.audit_log] == ["goal.create", "run.create", "run.start"]


@pytest.mark.asyncio
async def test_entrypoints_reject_missing_identity_and_private_operation() -> None:
    service = ApplicationService()
    missing_actor = await execute("create_goal", {"objective": "x"}, service=service)
    private = await execute(
        "_record",
        {**CONTEXT, "action": "x", "resource_type": "x", "resource_id": "x"},
        service=service,
    )
    assert missing_actor["success"] is False
    assert private == {
        "success": False,
        "data": None,
        "error": "a public application operation is required",
    }


def test_formal_web_and_mcp_entries_use_v3_service() -> None:
    import webauto.adapters.mcp_server as formal_mcp
    import webauto.adapters.web_server as formal_web

    assert formal_web.app.state.application_service is formal_web.service
    assert {item["name"] for item in formal_mcp.list_tools()} == {
        item["name"] for item in list_tools()
    }
    assert create_app(service=formal_web.service).state.application_service is formal_web.service


def test_entrypoint_sources_do_not_import_legacy_core_or_tool_backends() -> None:
    from pathlib import Path

    root = Path(__file__).parents[2]
    paths = [
        root / "src/webauto/application/cli.py",
        root / "src/webauto/application/mcp.py",
        root / "src/webauto/adapters/mcp_server.py",
        root / "src/webauto/adapters/web_server.py",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for forbidden in ("from Core", "import Core", "console_backend", "credential_backend"):
        assert forbidden not in source


class _ButlerBackend:
    async def execute(self, request):
        return ButlerExecutionResult("succeeded", "done", {"url": request.context["urls"][0]})


@pytest.mark.asyncio
async def test_mcp_exposes_butler_and_setup_token_protected_settings(tmp_path) -> None:
    service = ApplicationService()
    store = RuntimeConfigStore(tmp_path)
    butler = ButlerService(service, _ButlerBackend())
    reply = await call_tool(
        "butler_message",
        {
            **CONTEXT,
            "mcp_token": store.mcp_authorizer.token(),
            "message": "打开 https://example.test 看看",
        },
        service=service,
        butler=butler,
        settings_store=store,
    )
    assert reply["success"] is True
    assert reply["data"]["kind"] == "completed"

    denied = await call_tool("settings_get", {"setup_token": "wrong"}, settings_store=store)
    assert denied["success"] is False
    allowed = await call_tool(
        "settings_get", {"setup_token": store.authorizer.token()}, settings_store=store
    )
    assert allowed["success"] is True
    assert allowed["data"]["secrets"]["database_url"] is False
