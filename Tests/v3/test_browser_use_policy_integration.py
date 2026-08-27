"""Real Browser Use registry compatibility for WebAuto's final navigation gate."""

from __future__ import annotations

import pytest

from webauto.agent_backends import (
    BrowserAgentPolicyViolation,
    BrowserAgentSecurityPolicy,
    BrowserUseReadOnlyToolsFactory,
)
from webauto.domain import AgentTaskRequest, Placement

pytest.importorskip("browser_use")


@pytest.mark.asyncio
async def test_real_browser_use_navigate_action_is_policy_wrapped() -> None:
    tools = BrowserUseReadOnlyToolsFactory().create()
    request = AgentTaskRequest(
        run_id="real-tools-policy",
        objective="read the approved page",
        success_criteria=("return evidence",),
        profile_id="personal",
        placement=Placement.DESKTOP_MANAGED,
        allowed_domains=("example.com",),
    )
    BrowserAgentSecurityPolicy().protect_tools(tools, request)
    navigate = tools.registry.registry.actions["navigate"]
    params = navigate.param_model(url="http://127.0.0.1/private")

    with pytest.raises(BrowserAgentPolicyViolation, match="private"):
        await navigate.function(params=params)

    assert "WebAuto blocks local/private networks" in navigate.description
