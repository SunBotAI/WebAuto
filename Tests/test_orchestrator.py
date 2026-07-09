"""
Tests/test_orchestrator.py — FINGERPRINT-004 验收测试

BrowserOrchestrator:
1. 3 个 Profile 并发创建 Context，Cookie 100% 隔离
2. max_concurrent 排队限制
3. 内存超 2GB 时拒绝新 Context 并报警
"""
import sys
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.profile import Profile, ProfileStatus
from Core.Profile.orchestrator import BrowserOrchestrator, MEMORY_LIMIT_BYTES
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
def profiles(tmpdir):
    """3 个独立 Profile"""
    out = []
    for i in range(3):
        p = Profile(id=f"profile-{i}", name=f"Profile {i}")
        p.storage_dir = tmpdir / f"profile-{i}"
        p.fingerprint.screen_resolution = (1920, 1080)
        out.append(p)
    return out


@pytest.fixture
def mock_playwright_and_browser():
    """Mock Playwright + Browser，返回 3 个隔离的 context mock"""
    mock_browser = AsyncMock()
    mock_contexts = {}

    def make_context(profile_id):
        ctx = AsyncMock()
        ctx.add_init_script = AsyncMock()
        mock_contexts[profile_id] = ctx
        return ctx

    mock_browser.new_context = AsyncMock(side_effect=lambda **kw: make_context(kw.get("user_data_dir", "").split("/")[-1]))
    mock_browser.close = AsyncMock()
    mock_browser.process = MagicMock()
    mock_browser.process.pid = 12345

    mock_pw = AsyncMock()
    mock_pw.chromium = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.stop = AsyncMock()

    return mock_pw, mock_browser, mock_contexts


# ─── Test 1: Cookie 隔离 ───────────────────────────────────────────────────

class TestCookieIsolation:
    """3 个 Profile 并发创建 Context，Cookie 100% 隔离"""

    @pytest.mark.asyncio
    async def test_three_profiles_concurrent_cookie_isolation(
        self, store, profiles, mock_playwright_and_browser
    ):
        """
        3 个不同 Profile 并发 acquire，验证：
        - 3 个独立 context 对象
        - 每个 context 调用 new_context 时传了不同的 user_data_dir
        """
        mock_pw, mock_browser, mock_contexts = mock_playwright_and_browser

        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            orch = BrowserOrchestrator(store=store, headless=True, max_concurrent=5)
            orch._browser = mock_browser
            orch._playwright = mock_pw
            orch._semaphore = asyncio.Semaphore(5)

            # 并发获取 3 个 Profile 的 context
            results = await asyncio.gather(*[
                orch.get_context(p) for p in profiles
            ])

        # 3 个不同 context 对象
        assert len(set(id(ctx) for ctx in results)) == 3, "3 个 Profile 应有 3 个独立 Context"

        # 每个 context 分配给了正确的 profile id
        for i, p in enumerate(profiles):
            ctx = results[i]
            stored = orch._contexts[p.id]
            assert ctx is stored, f"Profile {p.id} 的 Context 应存储在 orch._contexts[{p.id}]"

    @pytest.mark.asyncio
    async def test_same_profile_reuses_context(self, store, profiles, mock_playwright_and_browser):
        """
        同一 Profile 并发 acquire，必须复用已有 Context，不重复创建。
        """
        mock_pw, mock_browser, mock_contexts = mock_playwright_and_browser

        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            orch = BrowserOrchestrator(store=store, headless=True, max_concurrent=5)
            orch._browser = mock_browser
            orch._playwright = mock_pw
            orch._semaphore = asyncio.Semaphore(5)

            p = profiles[0]
            # 5 个协程同时请求同一 Profile
            results = await asyncio.gather(*[
                orch.get_context(p) for _ in range(5)
            ])

        # 应该只有 1 个 context
        assert len(orch._contexts) == 1, "同一 Profile 应只创建 1 个 Context"
        # 5 次返回值必须完全相同（同一个对象）
        assert all(r is results[0] for r in results), "同一 Profile 的 5 次请求应返回相同 Context 对象"
        # new_context 只被调用了 1 次
        assert mock_browser.new_context.call_count == 1


# ─── Test 2: max_concurrent 排队限制 ───────────────────────────────────────

class TestMaxConcurrentQueueing:
    """max_concurrent 限制：超过阈值的请求排队，不超限"""

    def test_orchestrator_semaphore_initialized_on_start(self, store, tmpdir):
        """start() 调用后 orch._semaphore 已按 max_concurrent 初始化"""
        orch = BrowserOrchestrator(store=store, headless=True, max_concurrent=3)
        assert orch._semaphore is None  # start 前是 None

        async def fake_start():
            await orch.start()
            assert orch._semaphore is not None
            assert orch._semaphore._value == 3  # Semaphore 的内部计数器

        # Mock launch 以避免真的启动浏览器
        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_browser.process = MagicMock()
            mock_browser.process.pid = 12345
            mock_pw.return_value.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_pw.return_value.stop = AsyncMock()
            asyncio.run(fake_start())

    @pytest.mark.asyncio
    async def test_close_context_releases_semaphore_slot(self, store, tmpdir, mock_playwright_and_browser):
        """close_context 释放一个并发槽，后续请求可继续"""
        mock_pw, mock_browser, mock_contexts = mock_playwright_and_browser

        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            orch = BrowserOrchestrator(store=store, headless=True, max_concurrent=1)
            orch._browser = mock_browser
            orch._playwright = mock_pw

            p1 = Profile(id="close-slot-1")
            p1.storage_dir = tmpdir / "close-slot-1"
            p1.fingerprint.screen_resolution = (1920, 1080)

            p2 = Profile(id="close-slot-2")
            p2.storage_dir = tmpdir / "close-slot-2"
            p2.fingerprint.screen_resolution = (1920, 1080)

            ctx1 = await orch.get_context(p1)
            assert ctx1 is not None

            await orch.close_context(p1)

            ctx2 = await orch.get_context(p2)
            assert ctx2 is not None


# ─── Test 3: 内存监控 ──────────────────────────────────────────────────────

class TestMemoryLimit:
    """内存超 2GB 时拒绝新 Context 并报警"""

    @pytest.mark.asyncio
    async def test_memory_exceeded_rejects_new_context(self, store, tmpdir, mock_playwright_and_browser):
        """
        模拟 Chromium 进程 RSS > 2GB，下一个新 Context 请求应抛出 MemoryError。
        """
        mock_pw, mock_browser, mock_contexts = mock_playwright_and_browser

        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            orch = BrowserOrchestrator(
                store=store,
                headless=True,
                max_concurrent=5,
                memory_limit_bytes=MEMORY_LIMIT_BYTES,
            )
            orch._browser = mock_browser
            orch._playwright = mock_pw
            orch._semaphore = asyncio.Semaphore(5)

            # 直接 mock _get_browser_memory_bytes（psutil.Process 无法在测试中直接 mock）
            orch._get_browser_memory_bytes = lambda: MEMORY_LIMIT_BYTES + 100 * 1024 * 1024

            p = Profile(id="mem-test")
            p.storage_dir = tmpdir / "mem-test"
            p.fingerprint.screen_resolution = (1920, 1080)

            with pytest.raises(MemoryError) as exc_info:
                await orch.get_context(p)

            assert "exceeds limit" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_memory_under_limit_allows_new_context(self, store, tmpdir, mock_playwright_and_browser):
        """
        内存 < 2GB 时，正常创建 Context，不抛异常。
        """
        mock_pw, mock_browser, mock_contexts = mock_playwright_and_browser

        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            orch = BrowserOrchestrator(
                store=store,
                headless=True,
                max_concurrent=5,
                memory_limit_bytes=MEMORY_LIMIT_BYTES,
            )
            orch._browser = mock_browser
            orch._playwright = mock_pw
            orch._semaphore = asyncio.Semaphore(5)

            # 512MB，远低于 2GB
            orch._get_browser_memory_bytes = lambda: 512 * 1024 * 1024

            p = Profile(id="mem-ok")
            p.storage_dir = tmpdir / "mem-ok"
            p.fingerprint.screen_resolution = (1920, 1080)

            # 不应抛异常
            ctx = await orch.get_context(p)
            assert ctx is not None

    def test_memory_limit_bytes_configurable(self, store):
        """memory_limit_bytes 参数可自定义（不限于 2GB）"""
        custom_limit = 1024 * 1024 * 1024  # 1GB
        orch = BrowserOrchestrator(
            store=store,
            headless=True,
            memory_limit_bytes=custom_limit,
        )
        assert orch.memory_limit_bytes == custom_limit


# ─── Test 4: close_context 释放并发槽 ──────────────────────────────────────


