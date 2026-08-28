"""MCP authentication is token-based and never trusts caller-supplied roles."""

from __future__ import annotations

import pytest

from webauto.application import ApplicationService
from webauto.application.mcp import call_tool
from webauto.application.settings import RuntimeConfigStore


@pytest.mark.asyncio
async def test_mcp_requires_independent_token_and_ignores_role_payload(tmp_path) -> None:
    service = ApplicationService()
    store = RuntimeConfigStore(tmp_path / "var")
    goal = {
        "objective": "read the approved page",
        "success_criteria": ["result verified"],
    }

    missing = await call_tool(
        "goal_create",
        {**goal, "user_id": "forged", "tenant_id": "other", "roles": ["admin"]},
        service=service,
        settings_store=store,
    )
    assert missing["success"] is False
    assert missing["error"] == "valid MCP token required"

    created = await call_tool(
        "goal_create",
        {
            **goal,
            "mcp_token": store.mcp_authorizer.token(),
            "user_id": "forged",
            "tenant_id": "other",
            "roles": ["viewer"],
        },
        service=service,
        settings_store=store,
    )
    assert created["success"] is True
    assert service.audit_log[-1].actor_id == "mcp-local"
    assert service.audit_log[-1].tenant_id == "local"
