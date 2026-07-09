"""
Tests/test_browser_args_extensions.py — T-057 browser_args + extensions 消费测试

验证：
1. browser_args 注入到 chromium.launch(args=[...])
2. extensions 传入 new_context(extensions=[...])
3. browser_args 去重不重复
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from Core.Profile import Profile
from Core.Profile.orchestrator import BrowserOrchestrator
from Core.Profile.store import ProfileStore


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return ProfileStore(base_dir=tmp_path)


@pytest.fixture
def profile_with_args(tmp_path, store):
    p = Profile(id="test-args-ext", name="Test Args & Extensions")
    p.browser_args = [
        "--disable-auto-update",
        "--proxy-bypass-list=localhost",
    ]
    p.extensions = ["/path/to/ext1", "/path/to/ext2"]
    p.fingerprint.locale = "zh-CN"
    p.fingerprint.timezone = "Asia/Shanghai"
    p.fingerprint.screen_resolution = (1920, 1080)
    store.create(p)
    return p


@pytest.fixture
def profile_no_args(tmp_path, store):
    p = Profile(id="test-no-args", name="No Extra Args")
    p.fingerprint.locale = "en-US"
    p.fingerprint.timezone = "America/New_York"
    p.fingerprint.screen_resolution = (1280, 720)
    store.create(p)
    return p


# ─── Test: start() merges browser_args ──────────────────────────────────────

@pytest.mark.asyncio
async def test_browser_args_merged_in_start(store, profile_with_args):
    """start(browser_args=[...]) 正确合并到 launch(args=[...])"""
    captured_args = []

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(side_effect=lambda **kw: captured_args.append(kw.get("args")) or _fake_browser())
    mock_chromium.new_context = AsyncMock(return_value=_fake_context())

    mock_playwright = MagicMock()
    mock_playwright.chromium = mock_chromium
    # async_playwright() returns pw instance; .start() must return it too
    mock_playwright.start = AsyncMock(return_value=mock_playwright)
    mock_playwright.stop = AsyncMock()

    orch = BrowserOrchestrator(store=store, headless=True)

    with patch("Core.Profile.orchestrator.async_playwright", return_value=mock_playwright):
        await orch.start(browser_args=profile_with_args.browser_args)

    assert len(captured_args) == 1, f"launch called {len(captured_args)} times, expected 1"
    args = captured_args[0]
    # 基础参数保留
    assert "--disable-blink-features=AutomationControlled" in args
    assert "--no-sandbox" in args
    # 自定义参数合并
    assert "--disable-auto-update" in args
    assert "--proxy-bypass-list=localhost" in args


@pytest.mark.asyncio
async def test_browser_args_deduplication(store, profile_with_args):
    """browser_args 去重：相同 key 只保留一个"""
    duplicate_args = ["--disable-auto-update", "--disable-auto-update"]  # 完全重复
    all_args = profile_with_args.browser_args + duplicate_args

    captured_args = []

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(side_effect=lambda **kw: captured_args.append(kw.get("args")) or _fake_browser())
    mock_chromium.new_context = AsyncMock(return_value=_fake_context())

    mock_playwright = MagicMock()
    mock_playwright.chromium = mock_chromium
    mock_playwright.start = AsyncMock(return_value=mock_playwright)
    mock_playwright.stop = AsyncMock()

    orch = BrowserOrchestrator(store=store, headless=True)

    with patch("Core.Profile.orchestrator.async_playwright", return_value=mock_playwright):
        await orch.start(browser_args=all_args)

    count = captured_args[0].count("--disable-auto-update")
    assert count == 1, f"--disable-auto-update appears {count} times, expected 1"


@pytest.mark.asyncio
async def test_start_without_browser_args(store):
    """start() 不传 browser_args 时只用基础参数启动"""
    captured_args = []

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(side_effect=lambda **kw: captured_args.append(kw.get("args")) or _fake_browser())
    mock_chromium.new_context = AsyncMock(return_value=_fake_context())

    mock_playwright = MagicMock()
    mock_playwright.chromium = mock_chromium
    mock_playwright.start = AsyncMock(return_value=mock_playwright)
    mock_playwright.stop = AsyncMock()

    orch = BrowserOrchestrator(store=store, headless=True)

    with patch("Core.Profile.orchestrator.async_playwright", return_value=mock_playwright):
        await orch.start()  # 不传 browser_args

    args = captured_args[0]
    assert "--disable-blink-features=AutomationControlled" in args
    assert "--no-sandbox" in args
    assert "--test-flag" not in args  # 没有混入自定义参数


# ─── Test: extensions 传入 new_context ──────────────────────────────────────

@pytest.mark.asyncio
async def test_extensions_passed_to_new_context(store, profile_with_args):
    """profile.extensions 传入 new_context(extensions=[...])"""
    captured_options = []

    async def capture_new_context(**kwargs):
        captured_options.append(kwargs)
        ctx = _fake_context()
        return ctx

    mock_browser = _fake_browser()
    mock_browser.new_context = capture_new_context

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)
    mock_chromium.new_context = capture_new_context

    mock_playwright = MagicMock()
    mock_playwright.chromium = mock_chromium
    mock_playwright.start = AsyncMock()
    mock_playwright.stop = AsyncMock()

    orch = BrowserOrchestrator(store=store, headless=True)
    orch._browser = mock_browser
    orch._semaphore = asyncio.Semaphore(orch.max_concurrent)

    ctx = await orch.get_context(profile_with_args)

    assert len(captured_options) == 1
    assert captured_options[0].get("extensions") == ["/path/to/ext1", "/path/to/ext2"]
    assert ctx is not None


@pytest.mark.asyncio
async def test_no_extensions_not_passed(store, profile_no_args):
    """profile.extensions 为空时不传 extensions 参数"""
    captured_options = []

    async def capture_new_context(**kwargs):
        captured_options.append(kwargs)
        return _fake_context()

    mock_browser = _fake_browser()
    mock_browser.new_context = capture_new_context

    orch = BrowserOrchestrator(store=store, headless=True)
    orch._browser = mock_browser
    orch._semaphore = asyncio.Semaphore(orch.max_concurrent)

    ctx = await orch.get_context(profile_no_args)

    assert len(captured_options) == 1
    assert "extensions" not in captured_options[0]
    assert ctx is not None


# ─── Test: Profile 序列化保留 browser_args + extensions ─────────────────────

def test_profile_serialization(store, profile_with_args):
    """browser_args + extensions 正确序列化/反序列化"""
    data = profile_with_args.to_dict()
    assert data["browser_args"] == ["--disable-auto-update", "--proxy-bypass-list=localhost"]
    assert data["extensions"] == ["/path/to/ext1", "/path/to/ext2"]

    # 反序列化
    p2 = Profile.from_dict(data)
    assert p2.browser_args == ["--disable-auto-update", "--proxy-bypass-list=localhost"]
    assert p2.extensions == ["/path/to/ext1", "/path/to/ext2"]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _fake_browser():
    browser = MagicMock()
    browser.process = MagicMock()
    browser.process.pid = 99999
    return browser


def _fake_context():
    ctx = MagicMock()
    ctx.add_init_script = AsyncMock()
    ctx.close = AsyncMock()
    return ctx
