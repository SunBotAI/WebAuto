"""Web and MCP expose the same governed browser-session lifecycle."""

from __future__ import annotations

import pytest

from webauto.application import ApplicationService
from webauto.application.butler_service import ButlerExecutionResult, ButlerService
from webauto.application.control_api import create_app
from webauto.application.mcp import call_tool, list_tools
from webauto.application.settings import RuntimeConfigStore

HEADERS = {
    "x-user-id": "owner",
    "x-tenant-id": "personal",
    "x-roles": "operator",
}


class SessionBackend:
    def __init__(self) -> None:
        self.state = "closed"
        self.profile_id = "default"

    async def execute(self, request):
        return ButlerExecutionResult("failed", error="not used")

    async def open_browser_session(self, profile_id, allowed_domains):
        self.state = "connected"
        self.profile_id = profile_id
        return {
            "profile_id": profile_id,
            "allowed_domains": list(allowed_domains),
            "state": self.state,
        }

    async def browser_session_status(self, profile_id):
        return {"profile_id": profile_id, "state": self.state}

    async def close_browser_session(self, profile_id):
        self.state = "closed"
        return {"profile_id": profile_id, "state": self.state}


@pytest.mark.asyncio
async def test_http_browser_session_open_status_close() -> None:
    httpx = pytest.importorskip("httpx")
    backend = SessionBackend()
    service = ApplicationService()
    app = create_app(
        service,
        butler=ButlerService(service, backend),
        allow_trusted_headers=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        opened = await client.post(
            "/v1/browser-sessions",
            headers=HEADERS,
            json={"profile_id": "personal", "allowed_domains": ["example.test"]},
        )
        status = await client.get("/v1/browser-sessions/personal", headers=HEADERS)
        closed = await client.delete("/v1/browser-sessions/personal", headers=HEADERS)

    assert opened.json()["state"] == "connected"
    assert opened.json()["allowed_domains"] == ["example.test"]
    assert status.json()["state"] == "connected"
    assert closed.json()["state"] == "closed"


@pytest.mark.asyncio
async def test_mcp_browser_session_tools_use_token_and_shared_butler(tmp_path) -> None:
    backend = SessionBackend()
    service = ApplicationService()
    store = RuntimeConfigStore(tmp_path / "var")
    token = store.mcp_authorizer.token()
    butler = ButlerService(service, backend)

    opened = await call_tool(
        "browser_session_attach",
        {
            "mcp_token": token,
            "profile_id": "personal",
            "allowed_domains": ["example.test"],
        },
        service=service,
        butler=butler,
        settings_store=store,
    )
    status = await call_tool(
        "browser_session_status",
        {"mcp_token": token, "profile_id": "personal"},
        service=service,
        butler=butler,
        settings_store=store,
    )
    closed = await call_tool(
        "browser_session_close",
        {"mcp_token": token, "profile_id": "personal"},
        service=service,
        butler=butler,
        settings_store=store,
    )

    assert opened["data"]["state"] == "connected"
    assert status["data"]["state"] == "connected"
    assert closed["data"]["state"] == "closed"
    assert {
        "browser_session_create",
        "browser_session_attach",
        "browser_session_status",
        "browser_session_close",
    } <= {item["name"] for item in list_tools()}
