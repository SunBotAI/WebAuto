"""
Tests/test_proxy_pool_visual.py — T-097 代理池可视化测试

测试:
    geoip_route(url, profile_id)
    get_pool_visual_status()
    set_health_check_interval(minutes)
    pool.yaml 持久化 health_check_interval
"""

import pytest
import tempfile
import shutil
from pathlib import Path

from Core.Profile.pool import ProfilePool, _get_pool_instance, _set_pool_instance
from Core.Profile.store import ProfileStore
from Tools import proxy_backend as pb
from Core.Profile.proxy_rotator import ProxyRotator, ProxyState, ProxyEntry


@pytest.fixture
def rotator():
    """独立 ProxyRotator 用于测试。"""
    r = ProxyRotator()
    return r


@pytest.fixture
def pool_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


class TestGeoipRoute:
    def test_url_to_country_cn(self):
        """TLD .cn → CN"""
        from Tools.proxy_backend import _url_to_country
        assert _url_to_country("https://www.taobao.com/product") == "CN"
        assert _url_to_country("http://jd.cn") == "CN"

    def test_url_to_country_jp(self):
        """TLD .co.jp → JP"""
        from Tools.proxy_backend import _url_to_country
        assert _url_to_country("https://www.amazon.co.jp/dp/B08N5WRWNW") == "JP"

    def test_url_to_country_us(self):
        """TLD .com → US（默认）"""
        from Tools.proxy_backend import _url_to_country
        assert _url_to_country("https://www.amazon.com/dp/B08N5WRWNW") == "US"
        assert _url_to_country("https://google.com") == "US"

    def test_url_to_country_kr(self):
        """TLD .co.kr → KR"""
        from Tools.proxy_backend import _url_to_country
        assert _url_to_country("https://www.coupang.com") == "KR"

    def test_geoip_route_matches_region(self, rotator):
        """URL 匹配 region → 返回对应代理"""
        rotator.register("p1", ["http://proxy-us.example.com:8080"])
        rotator._proxy_pools["p1"][0].region = "US"
        rotator._proxy_pools["p1"][0].state = ProxyState.ACTIVE
        orig = pb._rotator
        pb._rotator = rotator
        try:
            result = pb.geoip_route("https://www.amazon.com/dp/xxx", "p1")
            assert result is not None
            assert result["country_matched"] == "US"
            assert "fallback" not in result  # 直接匹配，无 fallback
        finally:
            pb._rotator = orig

    def test_geoip_route_fallback(self, rotator):
        """无 region 匹配 → 返回任一 ACTIVE"""
        rotator.register("p1", ["http://proxy-jp.example.com:8080"])
        rotator._proxy_pools["p1"][0].region = "JP"
        rotator._proxy_pools["p1"][0].state = ProxyState.ACTIVE
        orig = pb._rotator
        pb._rotator = rotator
        try:
            result = pb.geoip_route("https://www.amazon.com/dp/xxx", "p1")
            assert result is not None
            assert result["fallback"] is True
        finally:
            pb._rotator = orig

    def test_geoip_route_no_pool(self):
        """profile 无代理池 → 返回 None"""
        orig = pb._rotator
        pb._rotator = None
        try:
            result = pb.geoip_route("https://www.amazon.co.jp/dp/xxx", "non-existent-profile")
            assert result is None
        finally:
            pb._rotator = orig


class TestPoolVisualStatus:
    def test_empty_pool(self, rotator):
        """空池 → 返回零值"""
        # 替换全局单例
        orig = pb._rotator
        pb._rotator = rotator
        try:
            status = pb.get_pool_visual_status()
            assert status["total"] == 0
            assert status["by_state"]["active"] == 0
        finally:
            pb._rotator = orig

    def test_pool_status_counts(self, rotator):
        """3个代理：active/cooldown/banned 各一"""
        rotator.register("p1", [
            "http://a1.example.com:8080",
            "http://a2.example.com:8080",
            "http://a3.example.com:8080",
        ])
        pool = rotator._proxy_pools["p1"]
        pool[0].state = ProxyState.ACTIVE
        pool[1].state = ProxyState.COOLDOWN
        pool[2].state = ProxyState.BANNED
        pool[0].region = "US"
        pool[1].region = "CN"
        pool[2].region = "JP"

        orig = pb._rotator
        pb._rotator = rotator
        try:
            status = pb.get_pool_visual_status()
            assert status["total"] == 3
            assert status["by_state"]["active"] == 1
            assert status["by_state"]["cooldown"] == 1
            assert status["by_state"]["banned"] == 1
            assert status["by_region"]["US"] == 1
            assert status["by_region"]["CN"] == 1
            assert status["by_region"]["JP"] == 1
            assert len(status["profiles"]) == 1
        finally:
            pb._rotator = orig


class TestHealthCheckInterval:
    def test_set_and_persist(self, pool_dir):
        """set_health_check_interval → 写入 pool.yaml"""
        store = ProfileStore(base_dir=pool_dir)
        pool = ProfilePool(store, max_concurrent=5)
        pool.set_health_check_interval(15)

        # 重启 pool（重新读取 pool.yaml）
        pool2 = ProfilePool(store, max_concurrent=5)
        assert pool2._health_check_interval == 15

        # 设为 0
        pool2.set_health_check_interval(0)
        pool3 = ProfilePool(store, max_concurrent=5)
        assert pool3._health_check_interval == 0

    def test_set_health_check_interval_via_backend(self, pool_dir):
        """proxy_backend.set_health_check_interval 正确调用 pool 方法"""
        store = ProfileStore(base_dir=pool_dir)
        pool = ProfilePool(store, max_concurrent=5)
        _set_pool_instance(pool)  # 模拟已注册单例

        pb.set_health_check_interval(30)
        assert pool._health_check_interval == 30

        # 重启验证持久化
        pool4 = ProfilePool(store, max_concurrent=5)
        assert pool4._health_check_interval == 30
