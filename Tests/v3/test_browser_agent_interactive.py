"""Low-risk interaction gates and persistent Browser Use profile sessions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from webauto.agent_backends import (
    LOW_RISK_BROWSER_USE_ACTIONS,
    BrowserAgentPolicyViolation,
    BrowserAgentSecurityPolicy,
    BrowserUseAdapter,
    BrowserUseInteractiveToolsFactory,
)
from webauto.agent_backends.action_policy import (
    APPROVAL_REQUIRED_MARKER,
    HUMAN_REQUIRED_MARKER,
)
from webauto.application.settings import RuntimeConfigStore
from webauto.domain import AgentTaskRequest, AgentTaskStatus, Placement
from webauto.runtime.browser import BrowserAgentSessionBridge


class FakeAction:
    def __init__(self, function, description: str = "") -> None:
        self.function = function
        self.description = description

    def model_copy(self, *, update):
        return FakeAction(
            update.get("function", self.function),
            update.get("description", self.description),
        )


class FakeNode:
    def __init__(self, text: str, **attributes: str) -> None:
        self._text = text
        self.attributes = attributes
        self.tag_name = "button"
        self.node_value = ""
        self.ax_node = None

    def get_meaningful_text_for_llm(self) -> str:
        return self._text


class FakeBrowserSession:
    def __init__(self, node: FakeNode) -> None:
        self.node = node

    async def get_element_by_index(self, index: int):
        assert index == 1
        return self.node


def request() -> AgentTaskRequest:
    return AgentTaskRequest(
        run_id="run-1",
        objective="search the approved site",
        success_criteria=("result returned",),
        profile_id="default",
        placement=Placement.DESKTOP_MANAGED,
        allowed_domains=("example.test",),
    )


def protected_tools():
    async def navigate(*, params, browser_session=None, **kwargs):
        return "navigated"

    async def click(*, params, browser_session, **kwargs):
        return "clicked"

    async def input_text(*, params, browser_session, **kwargs):
        return "typed"

    actions = {
        "navigate": FakeAction(navigate),
        "click": FakeAction(click),
        "input": FakeAction(input_text),
    }
    tools = SimpleNamespace(registry=SimpleNamespace(registry=SimpleNamespace(actions=actions)))
    return BrowserAgentSecurityPolicy().protect_tools(tools, request())


@pytest.mark.asyncio
async def test_safe_search_click_is_allowed_but_purchase_requires_approval() -> None:
    tools = protected_tools()
    params = SimpleNamespace(index=1)

    safe = FakeBrowserSession(FakeNode("搜索", type="submit"))
    assert (
        await tools.registry.registry.actions["click"].function(params=params, browser_session=safe)
        == "clicked"
    )

    purchase = FakeBrowserSession(FakeNode("立即购买", type="button"))
    with pytest.raises(BrowserAgentPolicyViolation, match=APPROVAL_REQUIRED_MARKER):
        await tools.registry.registry.actions["click"].function(
            params=params, browser_session=purchase
        )


@pytest.mark.asyncio
async def test_password_or_verification_input_requires_human_takeover() -> None:
    tools = protected_tools()
    params = SimpleNamespace(index=1, text="not-logged", clear=True)
    password = FakeBrowserSession(FakeNode("登录密码", type="password"))

    with pytest.raises(BrowserAgentPolicyViolation, match=HUMAN_REQUIRED_MARKER):
        await tools.registry.registry.actions["input"].function(
            params=params, browser_session=password
        )


class FakeRegistry:
    def __init__(self) -> None:
        self.registry = SimpleNamespace(
            actions={
                name: object()
                for name in LOW_RISK_BROWSER_USE_ACTIONS
                | {"upload_file", "evaluate", "write_file", "send_keys"}
            }
        )


class FakeTools:
    def __init__(self, **kwargs) -> None:
        self.registry = FakeRegistry()

    def exclude_action(self, name: str) -> None:
        self.registry.registry.actions.pop(name, None)


def test_interactive_factory_is_fail_closed_against_upstream_tools() -> None:
    factory = BrowserUseInteractiveToolsFactory(
        module_loader=lambda: SimpleNamespace(Tools=FakeTools)
    )
    tools = factory.create()
    assert set(tools.registry.registry.actions) == LOW_RISK_BROWSER_USE_ACTIONS
    assert not {"upload_file", "evaluate", "write_file", "send_keys"} & set(
        tools.registry.registry.actions
    )


class FakeHistory:
    def is_successful(self):
        return False

    def is_validated(self):
        return False

    def urls(self):
        return []

    def errors(self):
        return ["fixture stopped"]

    def final_result(self):
        return "fixture"


class FakeAgent:
    def __init__(self, browser) -> None:
        self.browser_session = browser

    async def run(self, *, max_steps):
        return FakeHistory()


class FakeBrowser:
    def __init__(self, options) -> None:
        self.options = options
        self.browser_profile = SimpleNamespace(
            allowed_domains=options["allowed_domains"],
            downloads_path=options["downloads_path"],
        )
        self.started = 0
        self.killed = 0
        self.stopped = 0

    async def start(self):
        self.started += 1

    async def kill(self):
        self.killed += 1

    async def stop(self):
        self.stopped += 1


class FakeRuntime:
    def __init__(self) -> None:
        self.browsers: list[FakeBrowser] = []

    def create_browser(self, **options):
        browser = FakeBrowser(options)
        self.browsers.append(browser)
        return browser

    def create_agent(self, **options):
        return FakeAgent(options["browser"])


class PermissivePolicy:
    def validate_request(self, request):
        return None

    def protect_tools(self, tools, request):
        return tools


@pytest.mark.asyncio
async def test_adapter_reuses_profile_browser_and_updates_domain_scope(tmp_path) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    runtime = FakeRuntime()
    adapter = BrowserUseAdapter(
        model_factory=lambda: object(),
        runtime=runtime,
        controlled_tools=object(),
        security_policy=PermissivePolicy(),
    )
    bridge = BrowserAgentSessionBridge(store)
    first_session = bridge.prepare(
        run_id="run-1", profile_id="default", allowed_domains=("one.test",)
    )
    second_session = bridge.prepare(
        run_id="run-2", profile_id="default", allowed_domains=("two.test",)
    )

    first = await adapter.run(request(), first_session)
    second = await adapter.run(
        request().model_copy(update={"run_id": "run-2", "allowed_domains": ("two.test",)}),
        second_session,
    )

    assert first.status == second.status == AgentTaskStatus.FAILED
    assert len(runtime.browsers) == 1
    assert runtime.browsers[0].browser_profile.allowed_domains == ["two.test"]
    opened = await adapter.open_session(second_session)
    assert opened["state"] == "connected"
    assert runtime.browsers[0].started == 1
    closed = await adapter.close_session("default")
    assert closed["state"] == "closed"
    assert runtime.browsers[0].killed == 1
