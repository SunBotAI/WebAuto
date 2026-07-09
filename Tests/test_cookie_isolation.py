"""
Tests/test_cookie_isolation.py — FINGERPRINT-007 验收测试

验收标准：
- 2 个 Profile 各创建 Context，设置不同 cookie，验证互相不可见
- Playwright BrowserContext cookie 天然隔离（不同 user_data_dir）
"""

import sys
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.profile import Profile, ProfileStatus
from Core.Profile.orchestrator import BrowserOrchestrator
from Core.Profile.store import ProfileStore


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def store(tmpdir):
    return ProfileStore(base_dir=tmpdir)


@pytest.fixture
def two_profiles(store):
    """2 个独立 Profile，各有独立 storage_dir"""
    profiles = []
    for i in range(2):
        p = Profile(id=f"cookie-profile-{i}", name=f"Cookie Profile {i}")
        p.fingerprint.screen_resolution = (1920, 1080)
        store.create(p)  # 设置 storage_dir 并创建目录
        profiles.append(p)
    return profiles


@pytest.fixture
def mock_browser_with_cookie_tracking():
    """
    Mock Browser，返回带 cookie 追踪的独立 context。

    每个 context 独立存储 cookies dict（模拟真实 BrowserContext 隔离），
    支持 add_cookies() 和 get_cookies()。
    """
    cookies_store: dict[str, list] = {}
    context_by_profile: dict[str, AsyncMock] = {}

    def make_context(profile_id):
        if profile_id in context_by_profile:
            return context_by_profile[profile_id]

        ctx = AsyncMock()

        async def mock_add_cookies(cookies):
            if profile_id not in cookies_store:
                cookies_store[profile_id] = []
            cookies_store[profile_id].extend(cookies)

        async def mock_get_cookies(urls=None):
            return list(cookies_store.get(profile_id, []))

        ctx.add_cookies = mock_add_cookies
        ctx.get_cookies = mock_get_cookies
        ctx.add_init_script = AsyncMock()
        ctx.close = AsyncMock()
        context_by_profile[profile_id] = ctx
        return ctx

    mock_browser = AsyncMock()

    async def new_context(**kw):
        # 从 user_data_dir 提取 profile_id（格式：.../profile-{id}/user-data）
        user_data = kw.get("user_data_dir", "")
        parts = user_data.split("/")
        # profile_id 在 user-data 的上一级目录
        profile_id = parts[-2] if parts[-1] == "user-data" else parts[-1]
        return make_context(profile_id)

    mock_browser.new_context = new_context
    mock_browser.close = AsyncMock()
    mock_browser.process = MagicMock()
    mock_browser.process.pid = 12345

    mock_pw = AsyncMock()
    mock_pw.chromium = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.stop = AsyncMock()

    return mock_pw, mock_browser, cookies_store


# ─── Cookie 隔离测试 ───────────────────────────────────────────────────────

class TestCookieIsolation:
    """2 个 Profile 的 Cookie 100% 隔离"""

    @pytest.mark.asyncio
    async def test_two_profiles_cookie_isolation(self, store, two_profiles, mock_browser_with_cookie_tracking):
        """
        2 个 Profile 各设置不同 cookie，验证互相完全不可见。

        核心保证：
        - 每个 Profile 有独立的 user_data_dir（Cookie/Storage/IndexedDB 隔离）
        - BrowserContext.cookies() 只返回本 context 的 cookie
        """
        mock_pw, mock_browser, cookies_store = mock_browser_with_cookie_tracking

        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            orch = BrowserOrchestrator(store=store, headless=True, max_concurrent=5)
            orch._browser = mock_browser
            orch._playwright = mock_pw
            orch._semaphore = asyncio.Semaphore(5)

            p0, p1 = two_profiles[0], two_profiles[1]

            # ── Profile 0: 借 Context，写入 cookie ──
            ctx0 = await orch.get_context(p0)
            await ctx0.add_cookies([
                {"name": "session_id", "value": "abc123", "domain": ".example.com"},
                {"name": "preference", "value": "dark_mode", "domain": ".example.com"},
            ])

            # ── Profile 1: 借 Context，写入不同 cookie ──
            ctx1 = await orch.get_context(p1)
            await ctx1.add_cookies([
                {"name": "session_id", "value": "xyz789", "domain": ".example.com"},
                {"name": "lang", "value": "zh-CN", "domain": ".example.com"},
            ])

            # ── 验证：Profile 0 看不见 Profile 1 的 cookie ──
            cookies_on_0 = await ctx0.get_cookies()
            cookie_names_0 = {c["name"] for c in cookies_on_0}

            assert "session_id" in cookie_names_0
            assert "preference" in cookie_names_0
            # Profile 1 的 cookie 不应在 Profile 0 的 cookies 里
            assert "lang" not in cookie_names_0, (
                "Profile 0 不应看见 Profile 1 的 cookie 'lang'（Cookie 隔离失败）"
            )

            # ── 验证：Profile 1 看不见 Profile 0 的 cookie ──
            cookies_on_1 = await ctx1.get_cookies()
            cookie_names_1 = {c["name"] for c in cookies_on_1}

            assert "session_id" in cookie_names_1
            assert "lang" in cookie_names_1
            assert "preference" not in cookie_names_1, (
                "Profile 1 不应看见 Profile 0 的 cookie 'preference'（Cookie 隔离失败）"
            )

            # ── 验证：session_id 值不同（同一个 cookie 名，不同 Profile 不同值）──
            session_0 = next(c["value"] for c in cookies_on_0 if c["name"] == "session_id")
            session_1 = next(c["value"] for c in cookies_on_1 if c["name"] == "session_id")
            assert session_0 == "abc123"
            assert session_1 == "xyz789"
            assert session_0 != session_1, "同 cookie 名但不同 Profile 必须值不同"

            await orch.stop()

    @pytest.mark.asyncio
    async def test_same_profile_reuses_context_cookie_state(self, store, two_profiles, mock_browser_with_cookie_tracking):
        """
        同一 Profile 两次 get_context，复用同一 Context，Cookie 状态保持。
        """
        mock_pw, mock_browser, cookies_store = mock_browser_with_cookie_tracking

        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            orch = BrowserOrchestrator(store=store, headless=True, max_concurrent=5)
            orch._browser = mock_browser
            orch._playwright = mock_pw
            orch._semaphore = asyncio.Semaphore(5)

            p = two_profiles[0]

            # 第一次获取 context，写入 cookie
            ctx1 = await orch.get_context(p)
            await ctx1.add_cookies([
                {"name": "token", "value": "secret-abc", "domain": ".secure.com"},
            ])

            # 第二次获取同一 profile，复用 context
            ctx2 = await orch.get_context(p)

            # 必须是同一 context 对象
            assert ctx1 is ctx2, "同一 Profile 两次 get_context 应复用已有 Context"

            # Cookie 状态保持
            cookies = await ctx2.get_cookies()
            token_value = next((c["value"] for c in cookies if c["name"] == "token"), None)
            assert token_value == "secret-abc", "Context 复用时 Cookie 状态应保持"

            await orch.stop()

    @pytest.mark.asyncio
    async def test_close_context_clears_from_orchestrator(self, store, two_profiles, mock_browser_with_cookie_tracking):
        """
        close_context() 后，Profile 的 Context 被关闭并从 orchestrator 移除。
        """
        mock_pw, mock_browser, cookies_store = mock_browser_with_cookie_tracking

        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            orch = BrowserOrchestrator(store=store, headless=True, max_concurrent=5)
            orch._browser = mock_browser
            orch._playwright = mock_pw
            orch._semaphore = asyncio.Semaphore(5)

            p = two_profiles[0]

            ctx = await orch.get_context(p)
            assert p.id in orch._contexts

            await orch.close_context(p)

            assert p.id not in orch._contexts, "close_context 后应从 orchestrator 移除"

            await orch.stop()

    @pytest.mark.asyncio
    async def test_different_user_data_dirs(self, store, two_profiles, mock_browser_with_cookie_tracking):
        """
        验证两个 Profile 创建 Context 时使用了不同的 user_data_dir。
        （user_data_dir 不同 = Cookie/LocalStorage/IndexedDB 完全隔离）
        """
        mock_pw, mock_browser, _ = mock_browser_with_cookie_tracking

        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            orch = BrowserOrchestrator(store=store, headless=True, max_concurrent=5)
            orch._browser = mock_browser
            orch._playwright = mock_pw
            orch._semaphore = asyncio.Semaphore(5)

            p0, p1 = two_profiles[0], two_profiles[1]

            # Mock new_context 记录调用参数
            new_context_calls = []
            original_new_context = mock_browser.new_context

            async def tracking_new_context(**kw):
                new_context_calls.append(kw)
                return await original_new_context(**kw)

            mock_browser.new_context = tracking_new_context

            await orch.get_context(p0)
            await orch.get_context(p1)

            # 验证两个 Profile 使用了不同的 user_data_dir
            assert len(new_context_calls) == 2
            user_data_dirs = [kw.get("user_data_dir", "") for kw in new_context_calls]

            # user_data_dir 格式：/tmp/xxx/cookie-profile-0/user-data
            assert "cookie-profile-0" in user_data_dirs[0]
            assert "cookie-profile-1" in user_data_dirs[1]
            assert user_data_dirs[0] != user_data_dirs[1], (
                "两个 Profile 必须使用不同的 user_data_dir（隔离保证）"
            )

            await orch.stop()
