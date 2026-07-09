"""
Tests/test_orchestrator_concurrency.py — T-059 验收测试

验证 BrowserOrchestrator per-profile lock 真并发（不是全局串锁）
"""
import sys
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.profile import Profile
from Core.Profile.orchestrator import BrowserOrchestrator
from Core.Profile.store import ProfileStore


class TestPerProfileConcurrency:
    """T-059: per-profile lock 实现真并发"""

    @pytest.mark.asyncio
    async def test_different_profiles_concurrent_not_serial(self):
        """
        5 个不同 Profile 并发 acquire，不应被全局锁串行化。

        验证方法：mock browser.new_context 耗时 50ms，
        - 串行：总耗时 >= 250ms（5 * 50ms）
        - 真并发：总耗时 < 150ms（接近 50ms）
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProfileStore(base_dir=Path(tmpdir))

            profiles = []
            for i in range(5):
                p = Profile(id=f"profile-{i}")
                p.storage_dir = Path(tmpdir) / f"profile-{i}"
                profiles.append(p)

            async def mock_new_context(**kwargs):
                await asyncio.sleep(0.05)
                ctx = AsyncMock()
                ctx.add_init_script = AsyncMock()
                return ctx

            mock_browser = AsyncMock()
            mock_browser.new_context = mock_new_context
            mock_browser.close = AsyncMock()
            mock_browser.process = MagicMock()
            mock_browser.process.pid = 12345

            mock_pw = AsyncMock()
            mock_pw.chromium = AsyncMock()
            mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_pw.stop = AsyncMock()

            orch = BrowserOrchestrator(store=store, headless=True)
            orch._browser = mock_browser
            orch._playwright = mock_pw
            orch._semaphore = asyncio.Semaphore(5)

            start = asyncio.get_event_loop().time()
            await asyncio.gather(*[orch.get_context(p) for p in profiles])
            total_time = asyncio.get_event_loop().time() - start

            assert total_time < 0.15, (
                f"5 个 Profile 并发 acquire 耗时 {total_time:.3f}s，"
                f"疑似串行（真并发应 < 0.15s）"
            )
            await orch.stop()

    @pytest.mark.asyncio
    async def test_same_profile_sequential_no_duplicate_context(self):
        """
        同一 Profile 并发 acquire，必须复用已有 Context，不重复创建。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProfileStore(base_dir=Path(tmpdir))
            profile = Profile(id="duplicate-test")
            profile.storage_dir = Path(tmpdir) / "duplicate-test"

            create_count = 0

            async def mock_new_context(**kwargs):
                nonlocal create_count
                create_count += 1
                await asyncio.sleep(0.05)
                ctx = AsyncMock()
                ctx.add_init_script = AsyncMock()
                return ctx

            mock_browser = AsyncMock()
            mock_browser.new_context = mock_new_context
            mock_browser.close = AsyncMock()
            mock_browser.process = MagicMock()
            mock_browser.process.pid = 12345

            mock_pw = AsyncMock()
            mock_pw.chromium = AsyncMock()
            mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_pw.stop = AsyncMock()

            orch = BrowserOrchestrator(store=store, headless=True)
            orch._browser = mock_browser
            orch._playwright = mock_pw
            orch._semaphore = asyncio.Semaphore(5)

            await asyncio.gather(*[
                orch.get_context(profile)
                for _ in range(5)
            ])

            assert create_count == 1, (
                f"同一 Profile 并发 acquire 应只创建 1 个 Context，"
                f"实际创建了 {create_count} 次"
            )
            await orch.stop()

    @pytest.mark.asyncio
    async def test_max_concurrent_configurable(self):
        """max_concurrent 参数可正常设置"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProfileStore(base_dir=Path(tmpdir))
            orch = BrowserOrchestrator(store=store, max_concurrent=3)
            assert orch.max_concurrent == 3

            orch2 = BrowserOrchestrator(store=store, max_concurrent=5)
            assert orch2.max_concurrent == 5
