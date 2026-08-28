"""MCP-first onboarding, tool exposure and transport authentication."""

from __future__ import annotations

import inspect
import json
import sys
import types

import pytest

from webauto.application import ApplicationService
from webauto.application.control_api import create_app
from webauto.application.mcp import list_agent_tools
from webauto.application.settings import RuntimeConfigStore


@pytest.mark.asyncio
async def test_mcp_client_config_is_setup_protected_and_contains_no_secret(tmp_path) -> None:
    httpx = pytest.importorskip("httpx")
    store = RuntimeConfigStore(tmp_path / "var")
    token = store.authorizer.token()
    mcp_token = store.mcp_authorizer.token()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_app(ApplicationService(), settings_store=store)
        ),
        base_url="http://test",
    ) as client:
        denied = await client.get("/v1/settings/mcp-client-config")
        response = await client.get(
            "/v1/settings/mcp-client-config",
            headers={"x-webauto-setup-token": token},
        )

    assert denied.status_code == 401
    assert response.status_code == 200
    data = response.json()
    serialized = json.dumps(data, ensure_ascii=False)
    assert data["mode"] == "mcp-first"
    assert data["web_role"] == "configuration_only"
    assert data["authentication"]["credential_injected_by_server"] is True
    assert data["authentication"]["credential_visible_to_agent"] is False
    assert token not in serialized
    assert mcp_token not in serialized
    assert "browser_open" in data["tool_names"]
    assert not any(name.startswith("settings_") for name in data["tool_names"])
    assert data["tool_count"] == len(list_agent_tools())


class _FakeFastMCP:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.tools = {}

    def add_tool(self, function, *, name, description) -> None:
        self.tools[name] = function


@pytest.mark.asyncio
async def test_stdio_injects_local_auth_but_http_does_not(monkeypatch, tmp_path) -> None:
    fake_package = types.ModuleType("mcp")
    fake_server = types.ModuleType("mcp.server")
    fake_server.FastMCP = _FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp", fake_package)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server)

    from webauto.adapters.mcp_server import create_server

    store = RuntimeConfigStore(tmp_path / "var")
    stdio = create_server(trusted_local_stdio=True, settings_store=store)
    http = create_server(trusted_local_stdio=False, settings_store=store)

    assert not any(name.startswith("settings_") for name in stdio.tools)
    assert "allowed_domains" in inspect.signature(stdio.tools["browser_open"]).parameters
    assert "payload" not in inspect.signature(stdio.tools["browser_open"]).parameters
    accepted = await stdio.tools["browser_status"]()
    denied = await http.tools["browser_status"]({})
    assert accepted == {
        "success": True,
        "data": {"state": "closed"},
        "error": None,
    }
    assert denied["success"] is False
    assert denied["error"] == "valid MCP token required"
