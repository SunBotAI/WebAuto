"""
Tests/test_orchestrator_warmup.py — T-063 / T-010 验收测试
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.profile import Profile, NetworkConfig, FingerprintConfig
from Core.Profile.orchestrator import BrowserOrchestrator
from Core.Profile.store import ProfileStore


class TestWarmupCalibrate:
    """T-063: warmup 必须调用 calibrate() 而非 sync()"""

    @pytest.mark.asyncio
    async def test_warmup_calls_calibrate_not_sync(self):
        """验证 warmup 里 TimeSync 调用 calibrate() 而非 sync()"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("Core.TimeSync.TimeSync") as MockTS:
                mock_instance = AsyncMock()
                mock_instance.calibrate = AsyncMock()
                mock_instance.sync = AsyncMock()
                MockTS.return_value = mock_instance

                with patch.object(BrowserOrchestrator, "start", new_callable=AsyncMock):
                    store = ProfileStore(base_dir=Path(tmpdir))

                    p = Profile(id="warmup-test")
                    p.network.proxy_url = None  # 无代理

                    with patch.object(BrowserOrchestrator, "get_context", new_callable=AsyncMock) as mock_ctx:
                        mock_ctx.return_value = AsyncMock()

                        orch = BrowserOrchestrator(store=store, headless=True)
                        await orch.warmup([p], ntp_sync=True)

                        # 核心断言：calibrate 被调用，sync 没被调用
                        assert mock_instance.calibrate.called, "warmup 必须调用 TimeSync.calibrate()"
                        assert not mock_instance.sync.called, "warmup 不应该调用 TimeSync.sync()（那是 dead code）"

                    await orch.stop()

    @pytest.mark.asyncio
    async def test_warmup_no_ntp_sync_flag(self):
        """ntp_sync=False 时不实例化 TimeSync"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("Core.TimeSync.TimeSync") as MockTS:
                store = ProfileStore(base_dir=Path(tmpdir))
                p = Profile(id="warmup-no-ntp")
                p.network.proxy_url = None

                with patch.object(BrowserOrchestrator, "start", new_callable=AsyncMock):
                    with patch.object(BrowserOrchestrator, "get_context", new_callable=AsyncMock) as mock_ctx:
                        mock_ctx.return_value = AsyncMock()
                        orch = BrowserOrchestrator(store=store, headless=True)
                        await orch.warmup([p], ntp_sync=False)
                        assert not MockTS.called, "ntp_sync=False 时不应调用 TimeSync"
                    await orch.stop()


class TestNetworkProxyTuple:
    """T-010: get_playwright_proxy 必须返回三元组 (server, username, password)"""

    def test_proxy_url_with_embedded_auth(self):
        """URL 内嵌认证: http://user:pass@host:port"""
        nc = NetworkConfig(proxy_url="http://user1:pass1@1.2.3.4:8080")
        result = nc.get_playwright_proxy()
        assert result == ("http://1.2.3.4:8080", "user1", "pass1"), f"FAIL: {result}"

    def test_proxy_explicit_username_password(self):
        """显式 proxy_username / proxy_password 字段（优先级最高）"""
        nc = NetworkConfig(
            proxy_url="http://1.2.3.4:8080",
            proxy_username="u2",
            proxy_password="p2",
        )
        result = nc.get_playwright_proxy()
        assert result == ("http://1.2.3.4:8080", "u2", "p2"), f"FAIL: {result}"

    def test_proxy_url_with_explicit_overrides_embedded(self):
        """URL 内嵌 + 显式字段同时存在时，显式字段优先"""
        nc = NetworkConfig(
            proxy_url="http://embedded: creds@1.2.3.4:8080",
            proxy_username="explicit_user",
            proxy_password="explicit_pass",
        )
        result = nc.get_playwright_proxy()
        assert result == ("http://1.2.3.4:8080", "explicit_user", "explicit_pass"), f"FAIL: {result}"

    def test_proxy_no_auth(self):
        """无认证代理"""
        nc = NetworkConfig(proxy_url="http://1.2.3.4:8080")
        result = nc.get_playwright_proxy()
        assert result == ("http://1.2.3.4:8080", None, None), f"FAIL: {result}"

    def test_proxy_none(self):
        """无 proxy_url"""
        nc = NetworkConfig()
        result = nc.get_playwright_proxy()
        assert result is None, f"FAIL: {result}"

    def test_proxy_socks5_with_auth(self):
        """SOCKS5 带认证"""
        nc = NetworkConfig(proxy_url="socks5://suser:spass@5.6.7.8:1080")
        result = nc.get_playwright_proxy()
        assert result == ("socks5://5.6.7.8:1080", "suser", "spass"), f"FAIL: {result}"
