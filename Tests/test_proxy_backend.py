"""
Tests/test_proxy_backend.py — T-072 proxy_backend 单测

覆盖：CRUD + health 报表 + 批量启用/禁用 + 失效剔除
"""

from __future__ import annotations

import pytest

from Core.Profile.proxy_rotator import ProxyState
from Tools import proxy_backend as px


# ─── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_rotator():
    """每个测试重置单例"""
    px._rotator = None
    yield
    px._rotator = None


# ─── 注册 / 注销 ─────────────────────────────────────────────────────────────

class TestRegisterProxies:
    def test_register_new(self):
        ok = px.register_proxies("profile-1", ["http://p1:8080", "http://p2:8080"])
        assert ok is True
        proxies = px.list_proxies("profile-1")
        assert len(proxies) == 2
        assert proxies[0]["url"] == "http://p1:8080"

    def test_register_empty_returns_false(self):
        assert px.register_proxies("profile-empty", []) is False

    def test_unregister_existing(self):
        px.register_proxies("profile-2", ["http://a:8080"])
        assert px.unregister_proxies("profile-2") is True
        assert px.list_proxies("profile-2") == []

    def test_unregister_nonexistent_returns_false(self):
        assert px.unregister_proxies("profile-none") is False


# ─── 单个增删 ────────────────────────────────────────────────────────────────

class TestAddRemoveProxy:
    def setup_method(self):
        px.register_proxies("profile-add", ["http://first:8080"])

    def test_add_new_url(self):
        ok = px.add_proxy("profile-add", "http://second:8080")
        assert ok is True
        proxies = px.list_proxies("profile-add")
        assert len(proxies) == 2

    def test_add_duplicate_returns_false(self):
        assert px.add_proxy("profile-add", "http://first:8080") is False

    def test_remove_existing(self):
        ok = px.remove_proxy("profile-add", "http://first:8080")
        assert ok is True
        proxies = px.list_proxies("profile-add")
        assert len(proxies) == 0

    def test_remove_nonexistent_returns_false(self):
        assert px.remove_proxy("profile-add", "http://nowhere:8080") is False


# ─── Health 报表 ────────────────────────────────────────────────────────────

class TestProxyHealth:
    def test_health_unregistered_returns_none(self):
        assert px.get_proxy_health("nonexistent") is None

    def test_list_all_health_empty(self):
        assert px.list_all_health() == []

    def test_health_counts(self):
        px.register_proxies("health-p1", [
            "http://active:8080",
            "http://cooldown:8080",
        ])
        # 手动设一个 cooldown
        rotator = px._get_rotator()
        with rotator._lock:
            pool = rotator._proxy_pools["health-p1"]
            pool[1].state = ProxyState.COOLDOWN

        health = px.get_proxy_health("health-p1")
        assert health["total"] == 2
        assert health["active"] == 1
        assert health["cooldown"] == 1


# ─── 批量启用 / 禁用 ───────────────────────────────────────────────────────

class TestBatchEnableDisable:
    def test_disable_proxy(self):
        px.register_proxies("dis-p1", ["http://to-disable:8080"])
        ok = px.disable_proxy("dis-p1", "http://to-disable:8080")
        assert ok is True
        proxies = px.list_proxies("dis-p1")
        assert proxies[0]["state"] == "banned"

    def test_enable_proxy(self):
        px.register_proxies("en-p1", ["http://to-enable:8080"])
        px.disable_proxy("en-p1", "http://to-enable:8080")
        ok = px.enable_proxy("en-p1", "http://to-enable:8080")
        assert ok is True
        proxies = px.list_proxies("en-p1")
        assert proxies[0]["state"] == "active"

    def test_batch_disable(self):
        px.register_proxies("batch-p1", ["http://shared:8080"])
        px.register_proxies("batch-p2", ["http://shared:8080"])
        count = px.batch_disable("http://shared:8080")
        assert count == 2
        health1 = px.get_proxy_health("batch-p1")
        assert health1["proxies"][0]["state"] == "banned"

    def test_batch_enable(self):
        px.register_proxies("be-p1", ["http://shared2:8080"])
        px.register_proxies("be-p2", ["http://shared2:8080"])
        px.batch_disable("http://shared2:8080")
        count = px.batch_enable("http://shared2:8080")
        assert count == 2
        health1 = px.get_proxy_health("be-p1")
        assert health1["proxies"][0]["state"] == "active"


# ─── 失效剔除 ──────────────────────────────────────────────────────────────

class TestMarkProxyDead:
    def test_mark_dead(self):
        px.register_proxies("dead-p1", [
            "http://dead:8080",
            "http://alive:8080",
        ])
        ok = px.mark_proxy_dead("dead-p1", "http://dead:8080")
        assert ok is True
        proxies = px.list_proxies("dead-p1")
        states = {p["url"]: p["state"] for p in proxies}
        assert states["http://dead:8080"] == "banned"

    def test_mark_dead_switches_to_next(self):
        px.register_proxies("switch-p1", [
            "http://first:8080",
            "http://second:8080",
        ])
        status_before = px.get_rotator_status("switch-p1")
        initial_idx = status_before["current_index"]

        px.mark_proxy_dead("switch-p1", "http://first:8080")
        status_after = px.get_rotator_status("switch-p1")
        # 应切换到 second（index 1）
        assert status_after["current_index"] == 1

    def test_mark_dead_nonexistent_returns_false(self):
        px.register_proxies("dead-none", ["http://x:8080"])
        assert px.mark_proxy_dead("dead-none", "http://nonexistent:8080") is False


# ─── 失败重置 ───────────────────────────────────────────────────────────────

class TestResetFailures:
    def test_reset_failures(self):
        px.register_proxies("reset-p1", ["http://reset:8080"])
        rotator = px._get_rotator()
        with rotator._lock:
            pool = rotator._proxy_pools["reset-p1"]
            pool[0].consecutive_failures = 5

        ok = px.reset_proxy_failures("reset-p1", "http://reset:8080")
        assert ok is True
        proxies = px.list_proxies("reset-p1")
        assert proxies[0]["consecutive_failures"] == 0
