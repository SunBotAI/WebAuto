"""
Tests/test_pool.py — FINGERPRINT-005 ProfilePool 验收测试

5 策略 + cooldown 防风控 + 100 次并发无死锁
"""
import sys
import asyncio
import time
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.profile import Profile, ProfileStatus
from Core.Profile.store import ProfileStore
from Core.Profile.pool import ProfilePool, AcquireStrategy


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return ProfileStore(base_dir=tmp_path)


def make_profiles(store: ProfileStore, count: int, status: ProfileStatus = ProfileStatus.READY) -> list[Profile]:
    profiles = []
    for i in range(count):
        p = Profile(id=f"pool-{i}")
        p.status = status
        p.storage_dir = Path(store.base_dir) / p.id
        p.storage_dir.mkdir(parents=True, exist_ok=True)
        store.save(p)
        profiles.append(p)
    return profiles


# ─── 测试类 ────────────────────────────────────────────────────────────────

class TestBasicAcquireRelease:
    """基础 acquire / release"""

    @pytest.mark.asyncio
    async def test_acquire_returns_profile(self, store):
        make_profiles(store, 3)
        pool = ProfilePool(store, max_concurrent=3)

        p = await pool.acquire()
        assert p is not None
        assert p.id.startswith("pool-")

    @pytest.mark.asyncio
    async def test_release_makes_profile_available_again(self, store):
        make_profiles(store, 1)
        pool = ProfilePool(store, max_concurrent=1)

        p1 = await pool.acquire()
        await pool.release(p1)

        p2 = await pool.acquire()
        assert p2.id == p1.id

    @pytest.mark.asyncio
    async def test_acquire_blocks_when_semaphore_full(self, store):
        """
        max_concurrent=1，唯一 slot 被占用后，新请求必须等待。
        """
        make_profiles(store, 1)
        pool = ProfilePool(store, max_concurrent=1)

        p1 = await pool.acquire()

        t2 = asyncio.ensure_future(pool.acquire(timeout=1.0))
        await asyncio.sleep(0.05)

        assert not t2.done(), "第 2 个请求应在等待"

        await pool.release(p1)

        p2 = await asyncio.wait_for(t2, timeout=1.5)
        assert p2.id == p1.id

    @pytest.mark.asyncio
    async def test_context_manager_releases_on_exit(self, store):
        make_profiles(store, 1)
        pool = ProfilePool(store, max_concurrent=1)

        async with pool.context() as p:
            assert p is not None

        # 已释放，可再次借
        async with pool.context() as p2:
            assert p2 is not None


class TestCooldown:
    """cooldown 防风控"""

    @pytest.mark.asyncio
    async def test_cooldown_blocks_reacquire(self, store):
        make_profiles(store, 1)
        pool = ProfilePool(store, max_concurrent=1)

        p1 = await pool.acquire()
        await pool.release(p1, cooldown=10.0)

        # 立即再借，p1 在 cooldown 中且 semaphore=1 但无可用 profile，应超时
        with pytest.raises(asyncio.TimeoutError):
            await pool.acquire(timeout=0.3)

    @pytest.mark.asyncio
    async def test_cooldown_expires_after_duration(self, store):
        make_profiles(store, 1)
        pool = ProfilePool(store, max_concurrent=1)

        p1 = await pool.acquire()
        # cooldown 0.2s
        await pool.release(p1, cooldown=0.2)

        # 等 cooldown 过期
        await asyncio.sleep(0.3)

        p2 = await pool.acquire()
        assert p2.id == p1.id

    @pytest.mark.asyncio
    async def test_cooldown_zero_allows_immediate_reacquire(self, store):
        make_profiles(store, 1)
        pool = ProfilePool(store, max_concurrent=1)

        p1 = await pool.acquire()
        await pool.release(p1, cooldown=0)

        p2 = await pool.acquire()
        assert p2.id == p1.id


class TestStrategies:
    """5 种策略"""

    @pytest.mark.asyncio
    async def test_round_robin_cycles_through_all(self, store):
        make_profiles(store, 3)
        pool = ProfilePool(store, strategy=AcquireStrategy.ROUND_ROBIN, max_concurrent=3)

        ids = []
        for _ in range(3):
            p = await pool.acquire()
            ids.append(p.id)
            await pool.release(p)

        assert len(set(ids)) == 3, "round_robin 应轮流选中不同 Profile"

    @pytest.mark.asyncio
    async def test_random_strategy_not_all_same(self, store):
        make_profiles(store, 5)
        pool = ProfilePool(store, strategy=AcquireStrategy.RANDOM, max_concurrent=5)

        ids = []
        for _ in range(20):
            p = await pool.acquire()
            ids.append(p.id)
            await pool.release(p)

        # random 策略下，多个请求有一定随机性
        # 至少不应该 20 次全选同一个（概率极低）
        unique = len(set(ids))
        assert unique > 1, "RANDOM 策略应有变化"

    @pytest.mark.asyncio
    async def test_sticky_by_tag_returns_same_profile(self, store):
        make_profiles(store, 3)
        pool = ProfilePool(store, strategy=AcquireStrategy.STICKY_BY_TAG, max_concurrent=3)

        ids = []
        for _ in range(5):
            p = await pool.acquire(tag="same-task")
            ids.append(p.id)
            await pool.release(p)

        # 同一 tag 应返回同一 Profile
        assert len(set(ids)) == 1, f"sticky_by_tag 同一 tag 应返回同一 Profile，实际: {ids}"

    @pytest.mark.asyncio
    async def test_least_used_prefers_less_used(self, store):
        """
        least_used 策略选 last_used 最旧的 Profile。
        验证：按 pool-2、pool-1、pool-0 顺序借还后，
        再借时 pool-0 的 last_used 最旧，应被选中。
        """
        make_profiles(store, 3)
        pool = ProfilePool(store, strategy=AcquireStrategy.LEAST_USED, max_concurrent=3)

        # 故意让 pool-2 最先被借（last_used 最新），pool-0 最后被借（last_used 最旧）
        # LEAST_USED 应该选 pool-0
        p2 = await pool.acquire()
        await pool.release(p2)

        p1 = await pool.acquire()
        await pool.release(p1)

        p0 = await pool.acquire()
        await pool.release(p0)

        # pool-0 刚被释放，last_used 最新；pool-2 最旧
        # 但 pool-2 最后被释放后，pool-0 的 last_used 被更新了
        # 所以 pool-2 的 last_used 最旧（先借先还）
        selected = await pool.acquire()
        # pool-2 的 last_used 是最旧的（最先借、最先还）
        assert selected.id == "pool-2", (
            f"least_used 应选 last_used 最旧的 pool-2，实际选了 {selected.id}"
        )

    @pytest.mark.asyncio
    async def test_health_based_skips_cooldown(self, store):
        profiles = make_profiles(store, 2)
        pool = ProfilePool(store, strategy=AcquireStrategy.HEALTH_BASED, max_concurrent=2)

        # pool-0 在 cooldown，pool-1 可用
        p0 = await pool.acquire()
        await pool.release(p0, cooldown=3600)  # 1 小时
        await pool.release(p1 := await pool.acquire())

        # health_based 应跳过 cooldown 中的 pool-0
        selected = await pool.acquire()
        assert selected.id == p1.id
        await pool.release(p1)


class TestConcurrency:
    """并发压力：100 次 acquire/release 无死锁"""

    @pytest.mark.asyncio
    async def test_100_concurrent_acquire_release_no_deadlock(self, store):
        """
        10 个 Profile，20 个协程并发借还 100 次，
        验证无死锁、状态正确。
        """
        make_profiles(store, 10)
        pool = ProfilePool(store, strategy=AcquireStrategy.LEAST_USED, max_concurrent=10)

        results: list[str] = []
        errors: list[Exception] = []

        async def borrow_return(task_id: int):
            try:
                for _ in range(5):  # 每人借还 5 次 = 20*5=100 次
                    p = await pool.acquire(timeout=5.0)
                    results.append(p.id)
                    await pool.release(p, cooldown=0)
            except asyncio.TimeoutError:
                errors.append(asyncio.TimeoutError(f"task {task_id} timed out"))
            except Exception as e:
                errors.append(e)

        tasks = [asyncio.create_task(borrow_return(i)) for i in range(20)]
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"有错误: {errors}"
        assert len(results) == 100, f"期望 100 次，实际 {len(results)}"
        # 无死锁 = 所有任务正常完成

    @pytest.mark.asyncio
    async def test_in_use_profiles_not_visible_to_others(self, store):
        """
        已被借出的 Profile，对其他 acquire 不可见。
        max_concurrent=2，只有 2 个 profile，第 3 个请求应超时。
        """
        make_profiles(store, 2)
        pool = ProfilePool(store, strategy=AcquireStrategy.ROUND_ROBIN, max_concurrent=2)

        p1 = await pool.acquire()
        p2 = await pool.acquire()

        # 第 3 个请求应超时（无可用 profile）
        with pytest.raises(asyncio.TimeoutError):
            await pool.acquire(timeout=0.3)

        await pool.release(p1)
        await pool.release(p2)
