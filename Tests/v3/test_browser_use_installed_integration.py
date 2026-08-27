"""Optional installed-package smoke tests for the pinned Browser Use adapter."""

from pathlib import Path

import pytest

from webauto.agent_backends import (
    READ_ONLY_BROWSER_USE_ACTIONS,
    BrowserUseModelBridge,
    BrowserUseReadOnlyToolsFactory,
    DefaultBrowserUseRuntime,
)
from webauto.agent_backends.browser_use import BrowserUseTaskOutput
from webauto.application.settings import RuntimeConfigStore

browser_use = pytest.importorskip("browser_use")


def test_installed_browser_use_version_and_real_tool_registry() -> None:
    from importlib.metadata import version

    assert version("browser-use") == "0.13.7"
    tools = BrowserUseReadOnlyToolsFactory().create()
    actions = set(tools.registry.registry.actions)
    assert {"done", "search", "navigate", "extract"} <= actions
    assert actions <= READ_ONLY_BROWSER_USE_ACTIONS
    assert (
        not {
            "click",
            "input",
            "upload_file",
            "send_keys",
            "select_dropdown",
            "evaluate",
            "write_file",
            "replace_file",
            "read_file",
        }
        & actions
    )


def test_settings_connection_check_validates_real_browser_use(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    store.update(
        {
            "browser_agent": {
                "backend": "browser_use",
                "enabled": True,
            }
        },
        {},
    )

    result = store.test_connections()["browser_agent"]

    assert result["ok"] is True
    assert "Browser Use 0.13.7" in result["message"]
    assert "17 个受治理低风险交互动作" in result["message"]


def test_real_model_browser_and_agent_construction_without_network(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    store.update(
        {
            "browser": {
                "mode": "cdp",
                "cdp_endpoint": "http://127.0.0.1:9222",
            },
            "model": {
                "provider": "openai-compatible",
                "base_url": "https://model.example.test/v1",
                "model": "vision-model",
            },
        },
        {"model_api_key": "constructor-only-key"},
    )
    model = BrowserUseModelBridge().create(store)
    tools = BrowserUseReadOnlyToolsFactory().create()
    runtime = DefaultBrowserUseRuntime()
    browser = runtime.create_browser(
        cdp_url="http://127.0.0.1:9222",
        allowed_domains=["example.test"],
        accept_downloads=False,
        auto_download_pdfs=False,
        keep_alive=True,
    )

    agent = runtime.create_agent(
        task="Open the approved site and return sourced evidence",
        llm=model,
        judge_llm=BrowserUseModelBridge().create(store),
        browser=browser,
        tools=tools,
        output_model_schema=BrowserUseTaskOutput,
        use_judge=True,
        use_vision="auto",
        available_file_paths=[],
    )

    assert agent.output_model_schema is BrowserUseTaskOutput
    assert set(agent.tools.registry.registry.actions) <= READ_ONLY_BROWSER_USE_ACTIONS
