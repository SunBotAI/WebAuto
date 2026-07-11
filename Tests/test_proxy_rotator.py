"""
Tests/test_proxy_rotator.py — T-022 验收测试
代理轮换：连续失败 → cooldown/banned → 切换下一个代理
"""
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.proxy_rotator import (
    ProxyRotator,
    ProxyPolicy,
    ProxyState,
    ProxyEntry,
)


class TestProxyEntry:
    """ProxyEntry 单元"""

    def test_active_entry_is_available(self):
        entry = ProxyEntry(url="http://proxy1:8080")
        assert entry.is_available() is True

    def test_banned_entry_not_available(self):
        entry = ProxyEntry(url="http://proxy1:8080", state=ProxyState.BANNED)
        assert entry.is_available() is False

    def test_cooldown_entry_not_available_until_expired(self):
        entry = ProxyEntry(
            url="http://proxy1:8080",
            state=ProxyState.COOLDOWN,
            cooldown_until=time.time() + 3600,
        )
        assert entry.is_available() is False

    def test_cooldown_entry_recovers_when_expired(self):
        entry = ProxyEntry(
            url="http://proxy1:8080",
            state=ProxyState.COOLDOWN,
            cooldown_until=time.time() - 1,  # 已过期
        )
        assert entry.is_available() is True
        assert entry.state == ProxyState.ACTIVE
        assert entry.consecutive_failures == 0


class TestProxyPolicy:
    """ProxyPolicy 默认值"""

    def test_default_values(self):
        policy = ProxyPolicy()
        assert policy.max_failures == 3
        assert policy.cooldown_minutes == 30.0
        assert policy.max_proxies_per_profile == 10

    def test_custom_values(self):
        policy = ProxyPolicy(max_failures=5, cooldown_minutes=10.0)
        assert policy.max_failures == 5
        assert policy.cooldown_minutes == 10.0


class TestProxyRotatorRegister:
    """register / unregister"""

    def test_register_single_proxy(self):
        rotator = ProxyRotator()
        rotator.register("p1", proxy_pool=["http://proxy1:8080"])
        assert rotator.get_current_proxy("p1") == "http://proxy1:8080"

    def test_register_multiple_proxies(self):
        rotator = ProxyRotator()
        rotator.register("p1", proxy_pool=[
            "http://proxy1:8080",
            "http://proxy2:8080",
            "http://proxy3:8080",
        ])
        assert rotator.get_current_proxy("p1") == "http://proxy1:8080"

    def test_register_truncates_to_max(self):
        policy = ProxyPolicy(max_proxies_per_profile=2)
        rotator = ProxyRotator(policy=policy)
        rotator.register("p1", proxy_pool=[
            "http://p1", "http://p2", "http://p3", "http://p4",
        ])
        status = rotator.get_status("p1")
        assert len(status["proxies"]) == 2

    def test_unregister(self):
        rotator = ProxyRotator()
        rotator.register("p1", proxy_pool=["http://proxy1:8080"])
        rotator.unregister("p1")
        assert rotator.get_current_proxy("p1") is None

    def test_get_status(self):
        rotator = ProxyRotator()
        rotator.register("p1", proxy_pool=["http://p1", "http://p2"])
        status = rotator.get_status("p1")
        assert status["profile_id"] == "p1"
        assert status["current_index"] == 0
        assert len(status["proxies"]) == 2
        assert status["proxies"][0]["url"] == "http://p1"


class TestProxyRotatorSuccess:
    """成功回调重置计数器"""

    def test_on_success_resets_counter(self):
        rotator = ProxyRotator()
        rotator.register("p1", proxy_pool=["http://p1"])

        # 触发一次失败
        rotator.on_failure("p1")
        status = rotator.get_status("p1")
        assert status["proxies"][0]["consecutive_failures"] == 1

        # 成功
        rotator.on_success("p1")
        status = rotator.get_status("p1")
        assert status["proxies"][0]["consecutive_failures"] == 0
        assert status["proxies"][0]["state"] == ProxyState.ACTIVE.value


class TestProxyRotatorFailureRotation:
    """失败触发轮换"""

    def test_first_failure_no_rotation(self):
        rotator = ProxyRotator(ProxyPolicy(max_failures=3))
        rotator.register("p1", proxy_pool=["http://p1", "http://p2"])

        result = rotator.on_failure("p1")
        assert result == "http://p1"
        assert rotator.get_current_proxy("p1") == "http://p1"
        status = rotator.get_status("p1")
        assert status["proxies"][0]["consecutive_failures"] == 1

    def test_second_failure_no_rotation(self):
        rotator = ProxyRotator(ProxyPolicy(max_failures=3))
        rotator.register("p1", proxy_pool=["http://p1", "http://p2"])

        rotator.on_failure("p1")  # 1
        rotator.on_failure("p1")  # 2
        status = rotator.get_status("p1")
        assert status["proxies"][0]["consecutive_failures"] == 2
        assert rotator.get_current_proxy("p1") == "http://p1"

    def test_third_failure_triggers_cooldown_and_rotation(self):
        """
        连续 3 次失败 → p1 cooldown → 切换到 p2
        """
        rotator = ProxyRotator(ProxyPolicy(max_failures=3, cooldown_minutes=30))
        rotator.register("p1", proxy_pool=["http://p1", "http://p2"])

        rotator.on_failure("p1")  # 1
        rotator.on_failure("p1")  # 2
        new_proxy = rotator.on_failure("p1")  # 3 → trigger

        # p1 进入 cooldown
        status = rotator.get_status("p1")
        assert status["proxies"][0]["state"] == ProxyState.COOLDOWN.value
        assert status["proxies"][0]["consecutive_failures"] == 3

        # 切换到 p2
        assert new_proxy == "http://p2"
        assert rotator.get_current_proxy("p1") == "http://p2"
        # current_index 已更新为 p2 的 index=1
        status2 = rotator.get_status("p1")
        assert status2["current_index"] == 1

    def test_all_proxies_cooldown_returns_none(self):
        """
        所有代理都被 cooldown → 返回 None（调用方应 ban profile）
        """
        rotator = ProxyRotator(ProxyPolicy(max_failures=1, cooldown_minutes=30))
        rotator.register("p1", proxy_pool=["http://p1", "http://p2"])

        # 失败 p1 → 轮换到 p2
        rotator.on_failure("p1")
        # 失败 p2 → 全部 cooldown
        rotator.on_failure("p1")

        status = rotator.get_status("p1")
        assert status["proxies"][0]["state"] == ProxyState.COOLDOWN.value
        assert status["proxies"][1]["state"] == ProxyState.COOLDOWN.value
        assert rotator.get_current_proxy("p1") is None

    def test_failure_on_unregistered_profile_returns_none(self):
        rotator = ProxyRotator()
        result = rotator.on_failure("nonexistent")
        assert result is None


class TestProxyRotatorCooldownRecovery:
    """cooldown 到期自动恢复"""

    def test_cooldown_expires_and_proxy_available_again(self):
        policy = ProxyPolicy(max_failures=1, cooldown_minutes=0.05)  # 3 seconds
        rotator = ProxyRotator(policy=policy)
        rotator.register("p1", proxy_pool=["http://p1"])

        rotator.on_failure("p1")  # → cooldown
        assert rotator.get_current_proxy("p1") is None  # cooldown 中

        time.sleep(3.5)  # 等待 3s cooldown 到期

        # cooldown 已过，proxy 恢复可用
        assert rotator.get_current_proxy("p1") == "http://p1"
        status = rotator.get_status("p1")
        assert status["proxies"][0]["state"] == ProxyState.ACTIVE.value
        assert status["proxies"][0]["consecutive_failures"] == 0


class TestProxyRotatorReset:
    """reset 不改变代理池"""

    def test_reset_clears_counters(self):
        rotator = ProxyRotator(ProxyPolicy(max_failures=3))
        rotator.register("p1", proxy_pool=["http://p1"])

        rotator.on_failure("p1")
        rotator.on_failure("p1")
        rotator.reset("p1")

        status = rotator.get_status("p1")
        assert status["profile_consecutive_failures"] == 0
        assert status["proxies"][0]["consecutive_failures"] == 0
        # 代理池不变
        assert rotator.get_current_proxy("p1") == "http://p1"

    def test_reset_unknown_profile_noop(self):
        rotator = ProxyRotator()
        rotator.reset("nonexistent")  # 不抛异常


class TestProxyRotatorConcurrentSafety:
    """线程安全（basic）"""

    def test_register_and_query(self):
        """多线程 register / get_current_proxy 不崩溃"""
        import threading

        rotator = ProxyRotator()
        errors = []

        def worker(i):
            try:
                rotator.register(f"p{i}", proxy_pool=[f"http://p{i}:8080"])
                time.sleep(0.001)
                rotator.get_current_proxy(f"p{i}")
                rotator.get_status(f"p{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
