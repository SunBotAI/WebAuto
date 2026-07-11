"""
Tests/test_service_registry.py — T-073 service_registry 单测

覆盖：单例注册/拿取 + 线程安全 + configure_pool / configure_rotator
"""

from __future__ import annotations

import pytest
import threading
import time
from pathlib import Path

from Core.Profile import AcquireStrategy
from Core.Profile.proxy_rotator import ProxyPolicy
from Tools import service_registry as sr


# ─── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_registry():
    sr._reset_for_test()
    yield
    sr._reset_for_test()


# ─── 单例注册 / 拿取 ────────────────────────────────────────────────────────

class TestSingletonRegistration:
    def test_get_store_returns_same_instance(self):
        store1 = sr.get_store(Path("./tmp/sr-test1"))
        store2 = sr.get_store()
        assert store1 is store2

    def test_get_store_idempotent(self):
        s1 = sr.get_store(Path("./tmp/sr-test2"))
        s2 = sr.get_store(Path("./tmp/sr-test2"))
        assert s1 is s2

    def test_get_pool_returns_same_instance(self):
        pool1 = sr.get_pool(Path("./tmp/sr-test3"))
        pool2 = sr.get_pool()
        assert pool1 is pool2

    def test_get_rotator_returns_same_instance(self):
        r1 = sr.get_rotator()
        r2 = sr.get_rotator()
        assert r1 is r2

    def test_store_and_pool_share_same_store(self):
        store = sr.get_store(Path("./tmp/sr-test4"))
        pool = sr.get_pool(Path("./tmp/sr-test4"))
        # pool 内部用同一个 store
        assert pool.store is store


# ─── configure_pool ─────────────────────────────────────────────────────────

class TestConfigurePool:
    def test_set_strategy(self):
        pool = sr.get_pool(Path("./tmp/sr-test5"))
        sr.configure_pool(strategy="round_robin")
        assert pool.strategy == AcquireStrategy.ROUND_ROBIN

    def test_set_max_concurrent(self):
        pool = sr.get_pool(Path("./tmp/sr-test6"))
        sr.configure_pool(max_concurrent=7)
        assert pool.get_status()["max_concurrent"] == 7

    def test_set_max_concurrent_invalid_raises(self):
        sr.get_pool(Path("./tmp/sr-test7"))
        with pytest.raises(ValueError):
            sr.configure_pool(max_concurrent=0)


# ─── configure_rotator ─────────────────────────────────────────────────────

class TestConfigureRotator:
    def test_configure_rotator_defaults(self):
        r = sr.get_rotator()
        # 默认值
        assert r._policy.max_failures == 3
        assert r._policy.cooldown_minutes == 30.0

    def test_configure_rotator_custom(self):
        sr._reset_for_test()
        r = sr.get_rotator(max_failures=5, cooldown_minutes=15.0)
        assert r._policy.max_failures == 5
        assert r._policy.cooldown_minutes == 15.0

    def test_configure_rotator_runtime(self):
        r = sr.get_rotator()
        sr.configure_rotator(max_failures=7, cooldown_minutes=20.0)
        assert r._policy.max_failures == 7
        assert r._policy.cooldown_minutes == 20.0


# ─── 线程安全 ──────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_get_store_returns_same(self):
        results = []
        def get():
            s = sr.get_store(Path("./tmp/sr-test8"))
            results.append(s)
        threads = [threading.Thread(target=get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(set(results)) == 1  # 全部是同一实例

    def test_concurrent_get_rotator_returns_same(self):
        results = []
        def get():
            r = sr.get_rotator()
            results.append(r)
        threads = [threading.Thread(target=get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(set(results)) == 1


# ─── lifecycle context manager（T-093）─────────────────────────────────────

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_lifecycle_enter_starts_flush_loop(self):
        pool = sr.get_pool(Path("./tmp/sr-test9"))
        assert pool._flush_task is None or pool._flush_task.done()
        async with sr.lifecycle(Path("./tmp/sr-test9")):
            # flush loop 应该启动了
            assert pool._flush_task is not None
            assert not pool._flush_task.done()

    @pytest.mark.asyncio
    async def test_lifecycle_exit_stops_flush_loop(self):
        pool = sr.get_pool(Path("./tmp/sr-test10"))
        async with sr.lifecycle(Path("./tmp/sr-test10")):
            pass
        # flush loop 应该停止了
        assert pool._flush_task is None or pool._flush_task.done()

    @pytest.mark.asyncio
    async def test_lifecycle_exit_flushes_dirty_pages(self):
        pool = sr.get_pool(Path("./tmp/sr-test11"))
        # 创建一个 dirty profile
        from Core.Profile import Profile
        p = Profile(id="lifecycle-test", name="LifecycleTest")
        pool._dirty[p.id] = p  # 直接塞 dirty，不走 acquire
        async with sr.lifecycle(Path("./tmp/sr-test11")):
            pass
        # 退出后 dirty 应该是空的
        assert len(pool._dirty) == 0
        # 同时 flush loop 已停
        assert pool._flush_task is None or pool._flush_task.done()
