"""
Tests/test_profile_integration.py — FINGERPRINT-007 验收测试

验收标准：
- Profile warmup → 使用 → save → reload 后数据一致
- 完整生命周期：create → save → load → status 更新 → reload
"""

import sys
import asyncio
import tempfile
import time
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
def integration_profile(store):
    """用于完整生命周期测试的 Profile（自动创建 storage）"""
    p = Profile(id="integration-test", name="Integration Test Profile")
    p.fingerprint.canvas_seed = 42
    p.fingerprint.locale = "zh-CN"
    p.fingerprint.timezone = "Asia/Shanghai"
    p.fingerprint.screen_resolution = (1920, 1080)
    p.fingerprint.hardware_concurrency = 8
    p.fingerprint.device_memory = 8
    p.tags = ["test", "integration"]
    store.create(p)  # 设置 storage_dir 并创建目录
    return p


@pytest.fixture
def mock_orchestrator(store, tmpdir):
    """Mock 化的 BrowserOrchestrator（不启动真实浏览器）"""
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_context.add_init_script = AsyncMock()
    mock_context.add_cookies = AsyncMock()
    mock_context.get_cookies = AsyncMock(return_value=[])
    mock_context.close = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()
    mock_browser.process = MagicMock()
    mock_browser.process.pid = 12345

    mock_pw = AsyncMock()
    mock_pw.chromium = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.stop = AsyncMock()

    with patch("playwright.async_api.async_playwright", return_value=mock_pw):
        orch = BrowserOrchestrator(store=store, headless=True, max_concurrent=3)
        orch._browser = mock_browser
        orch._playwright = mock_pw
        orch._semaphore = asyncio.Semaphore(3)
        yield orch, mock_browser, mock_context


# ─── 生命周期测试 ─────────────────────────────────────────────────────────

class TestProfileLifecycle:
    """Profile 完整生命周期：create → warmup → use → save → reload"""

    @pytest.mark.asyncio
    async def test_profile_create_and_save(self, store, integration_profile):
        """Step 1: 创建 Profile 并保存到 store（store.create 已保存）"""
        p = integration_profile

        # 初始状态
        assert p.status == ProfileStatus.READY
        assert p.id == "integration-test"
        assert p.fingerprint.canvas_seed == 42

        # 验证文件存在（store.create 已创建）
        assert (store.base_dir / p.id / "config.yaml").exists()
        assert (store.base_dir / p.id / "fingerprint.json").exists()
        assert (store.base_dir / p.id / "meta.json").exists()

    @pytest.mark.asyncio
    async def test_profile_load_after_save(self, store, integration_profile):
        """Step 2: create 后 load，字段完全一致"""
        p = integration_profile
        # store.create 已保存，直接 load
        loaded = store.get(p.id)

        assert loaded.id == p.id
        assert loaded.name == p.name
        assert loaded.fingerprint.canvas_seed == p.fingerprint.canvas_seed
        assert loaded.fingerprint.locale == p.fingerprint.locale
        assert loaded.fingerprint.timezone == p.fingerprint.timezone
        assert loaded.fingerprint.screen_resolution == p.fingerprint.screen_resolution
        assert loaded.tags == p.tags

    @pytest.mark.asyncio
    async def test_profile_warmup_creates_context(self, store, integration_profile, mock_orchestrator):
        """Step 3: warmup 为 Profile 创建 BrowserContext"""
        orch, mock_browser, mock_context = mock_orchestrator
        p = integration_profile

        await orch.start()
        ctx = await orch.get_context(p)

        assert ctx is mock_context
        assert p.id in orch._contexts
        assert p.status == ProfileStatus.RUNNING

        await orch.stop()

    @pytest.mark.asyncio
    async def test_profile_status_update_after_context_close(self, store, integration_profile, mock_orchestrator):
        """Step 4: close_context 后 Profile 状态恢复 READY"""
        orch, mock_browser, mock_context = mock_orchestrator
        p = integration_profile

        await orch.start()
        await orch.get_context(p)
        assert p.status == ProfileStatus.RUNNING

        await orch.close_context(p)

        assert p.id not in orch._contexts
        assert p.status == ProfileStatus.READY

        await orch.stop()

    @pytest.mark.asyncio
    async def test_profile_save_after_use_preserves_state(self, store, integration_profile, mock_orchestrator):
        """Step 5: 使用后 save，reload 状态一致"""
        orch, mock_browser, mock_context = mock_orchestrator
        p = integration_profile

        await orch.start()
        ctx = await orch.get_context(p)

        await orch.close_context(p)

        store.save(p)

        # reload 验证
        loaded = store.get(p.id)
        assert loaded.id == p.id
        assert loaded.status == ProfileStatus.READY
        assert loaded.fingerprint.canvas_seed == p.fingerprint.canvas_seed
        assert loaded.fingerprint.locale == p.fingerprint.locale

        await orch.stop()

    @pytest.mark.asyncio
    async def test_profile_roundtrip_all_fields(self, store):
        """
        完整 roundtrip：创建 → 修改所有字段 → create → reload
        验证每个字段都正确持久化和恢复。
        """
        # 创建
        p = Profile(id="roundtrip-all", name="All Fields Test")
        p.fingerprint.canvas_seed = 999
        p.fingerprint.audio_seed = 888
        p.fingerprint.locale = "en-GB"
        p.fingerprint.timezone = "Europe/London"
        p.fingerprint.platform = "MacIntel"
        p.fingerprint.vendor = "Apple Inc."
        p.fingerprint.screen_resolution = (1440, 900)
        p.fingerprint.hardware_concurrency = 4
        p.fingerprint.device_memory = 4
        p.fingerprint.webgl_vendor = "Apple Inc."
        p.fingerprint.webgl_renderer = "Apple M1"
        p.tags = ["e2e", "full"]
        p.browser_args = ["--disable-blink-features"]
        p.extensions = ["/path/to/extension"]

        store.create(p)

        # reload
        loaded = store.get(p.id)

        # 验证所有字段
        assert loaded.id == "roundtrip-all"
        assert loaded.name == "All Fields Test"
        assert loaded.fingerprint.canvas_seed == 999
        assert loaded.fingerprint.audio_seed == 888
        assert loaded.fingerprint.locale == "en-GB"
        assert loaded.fingerprint.timezone == "Europe/London"
        assert loaded.fingerprint.platform == "MacIntel"
        assert loaded.fingerprint.vendor == "Apple Inc."
        assert loaded.fingerprint.screen_resolution == (1440, 900)
        assert loaded.fingerprint.hardware_concurrency == 4
        assert loaded.fingerprint.device_memory == 4
        assert loaded.tags == ["e2e", "full"]
        assert loaded.browser_args == ["--disable-blink-features"]
        assert loaded.extensions == ["/path/to/extension"]

    @pytest.mark.asyncio
    async def test_store_list_all_returns_saved_profiles(self, store):
        """ProfileStore.list_all() 返回所有已保存的 Profile"""
        ids = ["list-test-1", "list-test-2", "list-test-3"]
        for i, pid in enumerate(ids):
            p = Profile(id=pid, name=f"Profile {i}")
            store.create(p)

        all_profiles = store.list_all()
        loaded_ids = {pr.id for pr in all_profiles}

        for pid in ids:
            assert pid in loaded_ids, f"Profile {pid} 应在 list_all() 结果中"

    @pytest.mark.asyncio
    async def test_profile_delete_removes_from_store(self, store):
        """ProfileStore.delete() 完全删除 Profile"""
        p = Profile(id="to-delete", name="Will Be Deleted")
        store.create(p)

        assert (store.base_dir / "to-delete" / "config.yaml").exists()

        store.delete(p.id, wipe_storage=True)

        assert not (store.base_dir / "to-delete").exists(), \
               "delete(wipe_storage=True) 后 Profile 目录应不存在"

    @pytest.mark.asyncio
    async def test_apply_to_antidetect_persists_across_save_reload(self, store):
        """
        apply_to_antidetect 设置的值，在 create → reload 后仍然有效。
        """
        from Core.AntiDetect import AntiDetectConfig

        p = Profile(id="seed-persist", name="Seed Persistence Test")
        p.fingerprint.canvas_seed = 777
        p.fingerprint.locale = "de-DE"
        p.fingerprint.timezone = "Europe/Berlin"

        # 同步到 AntiDetectConfig
        cfg = AntiDetectConfig()
        p.apply_to_antidetect(cfg)

        assert cfg.fingerprint_seed == 777
        assert cfg.navigator_locale == "de-DE"
        assert cfg.timezone == "Europe/Berlin"

        store.create(p)
        loaded = store.get(p.id)

        # reload 后 apply_to_antidetect 仍有效
        cfg2 = AntiDetectConfig()
        loaded.apply_to_antidetect(cfg2)

        assert cfg2.fingerprint_seed == 777
        assert cfg2.navigator_locale == "de-DE"
        assert cfg2.timezone == "Europe/Berlin"
