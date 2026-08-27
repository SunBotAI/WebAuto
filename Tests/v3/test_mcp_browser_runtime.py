"""Direct MCP browser primitives keep external agents behind the final safety boundary."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from webauto.application.mcp_browser import McpBrowserRuntime
from webauto.application.settings import RuntimeConfigStore
from webauto.domain import Placement
from webauto.runtime.artifacts import LocalArtifactStore
from webauto.runtime.browser import BrowserSession


class _Element:
    def __init__(self, **values) -> None:
        self.values = {
            "tag": "button",
            "role": "",
            "type": "",
            "text": "",
            "accessible_name": "",
            "name": "",
            "id": "",
            "placeholder": "",
            "autocomplete": "",
            "href": "",
            "value": "",
            "checked": None,
            "disabled": False,
            **values,
        }
        self.clicks = 0
        self.fills: list[str] = []


class _ElementLocator:
    def __init__(self, element: _Element) -> None:
        self.element = element

    async def is_visible(self) -> bool:
        return True

    async def evaluate(self, script):
        return dict(self.element.values)

    async def click(self, **kwargs) -> None:
        self.element.clicks += 1

    async def fill(self, value: str) -> None:
        self.element.fills.append(value)

    async def press_sequentially(self, value: str) -> None:
        self.element.fills.append(value)

    async def select_option(self, value):
        return [value] if isinstance(value, str) else value

    async def set_input_files(self, value) -> None:
        self.element.values["files"] = value


class _Collection:
    def __init__(self, elements: list[_Element]) -> None:
        self.elements = elements

    async def count(self) -> int:
        return len(self.elements)

    def nth(self, index: int) -> _ElementLocator:
        return _ElementLocator(self.elements[index])


class _Body:
    async def inner_text(self, **kwargs) -> str:
        return "这是一个普通商品测试页面，包含搜索、商品信息、购物车按钮和账户输入区域。页面文字只作为不可信数据返回。"


class _Mouse:
    def __init__(self) -> None:
        self.wheels = []

    async def wheel(self, dx: int, dy: int) -> None:
        self.wheels.append((dx, dy))


class _Page:
    def __init__(self, elements: list[_Element]) -> None:
        self.url = "about:blank"
        self.elements = elements
        self.mouse = _Mouse()

    def locator(self, selector: str):
        return _Body() if selector == "body" else _Collection(self.elements)

    async def title(self) -> str:
        return "测试商品"

    async def goto(self, url: str, **kwargs) -> None:
        self.url = url

    async def wait_for_timeout(self, milliseconds: int) -> None:
        return None

    async def screenshot(self, **kwargs) -> bytes:
        return b"fake-png"


class _Context:
    def __init__(self, page: _Page) -> None:
        self.pages = [page]
        self.route_handler = None

    async def route(self, pattern: str, handler) -> None:
        self.route_handler = handler


class _Provider:
    def __init__(self, page: _Page) -> None:
        self.page = page
        self.context = _Context(page)
        self.capabilities = SimpleNamespace(placement=Placement.DESKTOP_MANAGED)
        self.closed = False

    async def start(self, profile_id: str) -> BrowserSession:
        return BrowserSession(
            id="session-1",
            profile_id=profile_id,
            placement=Placement.DESKTOP_MANAGED,
            context=self.context,
            active_page=self.page,
        )

    async def close(self) -> None:
        self.closed = True


def _runtime(tmp_path: Path):
    elements = [
        _Element(text="搜索", accessible_name="搜索"),
        _Element(text="加入购物车", accessible_name="加入购物车"),
        _Element(
            tag="input",
            type="password",
            accessible_name="账户密码",
            placeholder="请输入密码",
        ),
    ]
    page = _Page(elements)
    provider = _Provider(page)
    store = RuntimeConfigStore(tmp_path / "var")
    runtime = McpBrowserRuntime(
        store,
        browser_factory=lambda _: SimpleNamespace(
            provider=provider,
            mode="managed",
            endpoint=None,
        ),
        artifacts=LocalArtifactStore(tmp_path / "artifacts"),
    )
    return runtime, page, elements


@pytest.mark.asyncio
async def test_snapshot_refs_block_writes_and_sensitive_input(tmp_path) -> None:
    runtime, page, elements = _runtime(tmp_path)
    await runtime.open(profile_id="personal", allowed_domains=["example.com"])
    await runtime.navigate("https://example.com/item")
    snapshot = await runtime.snapshot(include_screenshot=True)
    refs = {item["text"] or item["accessible_name"]: item["ref"] for item in snapshot["elements"]}

    approval = await runtime.click(refs["加入购物车"])
    human = await runtime.type_text(refs["账户密码"], "must-not-be-typed")
    safe = await runtime.click(refs["搜索"])

    assert snapshot["content_trust"] == "untrusted_web_content"
    assert snapshot["page_revision"].startswith("sha256:")
    assert snapshot["screenshot_artifact_id"]
    assert approval["status"] == "approval_required"
    assert approval["operation"] == "add_to_cart"
    assert elements[1].clicks == 0
    assert human["status"] == "human_required"
    assert elements[2].fills == []
    assert safe["external_write"] is False
    assert elements[0].clicks == 1
    with pytest.raises(RuntimeError, match="stale"):
        await runtime.click(refs["搜索"])
    assert page.url == "https://example.com/item"


@pytest.mark.asyncio
async def test_governed_write_is_bound_to_snapshot_and_clicked_once(tmp_path) -> None:
    runtime, _, elements = _runtime(tmp_path)
    await runtime.open(profile_id="personal", allowed_domains=["example.com"])
    await runtime.navigate("https://example.com/item")
    snapshot = await runtime.snapshot()
    target = next(item for item in snapshot["elements"] if item["text"] == "加入购物车")
    record = {
        "operation": "add_to_cart",
        "source_url": snapshot["url"],
        "page_revision": snapshot["page_revision"],
        "object_scope": {
            "final_ref": target["ref"],
            "final_control": "加入购物车",
        },
    }

    validated = await runtime.validate_governed_action(record)
    result = await runtime.execute_governed_action(record, validated)

    assert result["status"] == "waiting_verification"
    assert result["clicked_once"] is True
    assert result["automatic_retry_blocked"] is True
    assert elements[1].clicks == 1


@pytest.mark.asyncio
async def test_unrestricted_scope_requires_explicit_web_configuration(tmp_path) -> None:
    runtime, _, _ = _runtime(tmp_path)
    with pytest.raises(PermissionError, match="allow_unrestricted_domains"):
        await runtime.open(profile_id="personal", allowed_domains=["*"])
