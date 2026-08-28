"""The Web surface is zero-configuration and configuration-only in MCP-first mode."""

import pytest

from webauto.application import ApplicationService
from webauto.application.control_api import create_app


@pytest.mark.asyncio
async def test_root_redirects_to_zero_configuration_surface() -> None:
    httpx = pytest.importorskip("httpx")
    app = create_app(ApplicationService())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        root = await client.get("/")
        response = await client.get("/setup")

    assert root.status_code == 307
    assert root.headers["location"] == "/setup"
    assert response.status_code == 200
    for label in (
        "WebAuto 配置中心",
        "不用填运维参数",
        "一键准备本机环境",
        "账号只在浏览器里登录",
        "连接你的智能体",
        "高级设置",
    ):
        assert label in response.text
    for contract in (
        "'/settings'",
        "'/settings/mcp-client-config'",
        "'/settings/prepare-local'",
        "'/settings/test'",
        "'/settings/detect-browser'",
        "'/settings/initialize-database'",
    ):
        assert contract in response.text
    for removed in (
        'id="setup-token"',
        'id="create-goal"',
        'id="vertical-workspaces"',
        'id="governed-actions"',
        "'/butler/messages'",
        "data-run-action",
        "x-webauto-setup-token",
    ):
        assert removed not in response.text
    assert "x-webauto-csrf-token" in response.text
    assert "webauto_session=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]