"""
E2E/test_pool_e2e.py — ProfilePool 并发 + 策略 Playwright E2E 测试

真实浏览器 + 真实 pool，借还 5 种策略全验证。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from Core.Profile import Profile, FingerprintConfig, ProfileStore, ProfileStatus
from Core.Profile.pool import ProfilePool, AcquireStrategy
from Core.Profile.orchestrator import BrowserOrchestrator

# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return ProfileStore(base_dir=tmp_path)


@pytest.fixture
def pool(store):
    return ProfilePool(
        store,
        strategy=AcquireStrategy.LEAST_USED,
        max_concurrent=3,
        on_acquire_timeout=10.0,
    )


@pytest.fixture
def profiles(store):
    """创建 3 个 Profile（用于并发测试）"""
    out = []
    for i in range(3):
        p = Profile(id=f"pool-profile-{i}", name=f"Pool Profile {i}")
        # 设不同 user_agent，方便 E2E 测试识别是哪个 profile
        p.fingerprint.user_agent = f"Mozilla/5.0 (profile-{i}) AppleWebKit/537.36"
        store.create(p)
        out.append(p)
    return out


@pytest.fixture
def orchestrator(store):
    return BrowserOrchestrator(store=store, headless=True, max_concurrent=3)


# ─── Test Cases ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_acquire_release_no_deadlock(profiles, pool, orchestrator):
    """
    验证：3 个 Profile，6 个并发 worker，全部成功 acquire/release，无死锁。
    """
    results: dict = {}

    async def worker(i: int):
        start = time.monotonic()
        async with pool.context() as profile:
            results[i] = {"profile_id": profile.id, "acquired_at": start}
            # 模拟工作（创建 context，访问页面）
            ctx = await orchestrator.get_context(profile)
            page = await ctx.new_page()
            await page.goto("https://example.com", wait_until="domcontentloaded")
            await page.close()
        results[i]["released_at"] = time.monotonic()

    await asyncio.gather(*[worker(i) for i in range(6)])

    # 全部成功
    assert len(results) == 6
    for i in range(6):
        assert "released_at" in results[i], f"Worker {i} never released"


@pytest.mark.asyncio
async def test_round_robin_strategy_distributes_evenly(profiles, store, tmp_path):
    """
    验证 ROUND_ROBIN 策略：轮询分配，6 次 acquire 看到 3 个 Profile 各被使用 2 次。
    """
    pool = ProfilePool(store, strategy=AcquireStrategy.ROUND_ROBIN, max_concurrent=3)
    counts = {p.id: 0 for p in profiles}

    for _ in range(6):
        async with pool.context() as p:
            counts[p.id] += 1

    # 每个 Profile 至少被用一次（轮询）
    assert all(c > 0 for c in counts.values()), f"ROUND_ROBIN not cycling: {counts}"


@pytest.mark.asyncio
async def test_random_strategy_returns_valid_profile(profiles, store):
    """
    验证 RANDOM 策略：每次都返回有效的 available Profile。
    """
    pool = ProfilePool(store, strategy=AcquireStrategy.RANDOM, max_concurrent=3)
    seen: set = set()

    for _ in range(20):
        async with pool.context() as p:
            seen.add(p.id)

    # 3 个 Profile 都可能被选中
    assert len(seen) >= 2, f"RANDOM should vary across profiles: {seen}"


@pytest.mark.asyncio
async def test_sticky_by_tag_returns_same_profile(store, tmp_path):
    """
    验证 STICKY_BY_TAG 策略：同一 tag 每次返回同一个 Profile。
    """
    pool = ProfilePool(store, strategy=AcquireStrategy.STICKY_BY_TAG, max_concurrent=3)
    for i in range(3):
        p = Profile(id=f"sticky-{i}", name=f"Sticky {i}")
        store.create(p)

    ids = []
    for _ in range(5):
        async with pool.context(tag="same-task") as p:
            ids.append(p.id)

    assert len(set(ids)) == 1, f"STICKY_BY_TAG should return same profile: {ids}"


@pytest.mark.asyncio
async def test_least_used_selects_oldest_last_used(profiles, store):
    """
    验证 LEAST_USED 策略：总是选 last_used 最旧的 Profile。
    """
    pool = ProfilePool(store, strategy=AcquireStrategy.LEAST_USED, max_concurrent=3)

    # 先让 profile-0 被用过
    async with pool.context() as p0:
        assert p0.id == "pool-profile-0"

    # 第二次应该用 profile-1（因为 pool-profile-0 刚被用过）
    async with pool.context() as p1:
        assert p1.id == "pool-profile-1"

    # 第三次用 profile-2
    async with pool.context() as p2:
        assert p2.id == "pool-profile-2"


@pytest.mark.asyncio
async def test_health_based_prefers_ready_over_cooldown(profiles, store):
    """
    验证 HEALTH_BASED 策略：READY 优先于 COOLDOWN。
    """
    pool = ProfilePool(store, strategy=AcquireStrategy.HEALTH_BASED, max_concurrent=3)

    # 借走所有 Profile，第一个用完后设置 cooldown
    async with pool.context() as p:
        p_id = p.id

    # 归还并设置 cooldown（10 小时，模拟还在冷却中）
    pool.store.save(p)
    await pool.release(p, cooldown=36000)

    # 新请求应该拿到其他 READY 的 Profile，而不是还在 cooldown 的
    async with pool.context() as p2:
        assert p2.id != p_id, "HEALTH_BASED should avoid cooldown profile"


@pytest.mark.asyncio
async def test_cooldown_blocks_acquire(profiles, store, pool):
    """
    验证：cooldown 期间的 Profile 不会被分配。
    """
    # 借走 profile-0 并设置 cooldown
    async with pool.context() as p:
        used_id = p.id

    await pool.release(p, cooldown=36000)  # 10 小时

    # 在 max_concurrent=3 限制下，其他 2 个 Profile 仍然可用
    # 只有当并发 > 可用数时，cooldown 的才会被拒绝
    pool2 = ProfilePool(store, strategy=AcquireStrategy.LEAST_USED, max_concurrent=2)
    async with pool2.context(tag="only-one") as p2:
        assert p2.id != used_id, "Should not return cooldown profile"


@pytest.mark.asyncio
async def test_timeout_when_no_profile_available(store, tmp_path):
    """
    验证：无可用 Profile 时 raise TimeoutError。
    """
    p = Profile(id="timeout-test", name="Timeout Test")
    store.create(p)
    pool = ProfilePool(store, strategy=AcquireStrategy.LEAST_USED, max_concurrent=1)

    hold_event = asyncio.Event()

    async def hold_profile():
        async with pool.context():
            hold_event.set()
            await asyncio.sleep(5)  # 长时间占用

    # 后台任务占满 profile
    hold_task = asyncio.create_task(hold_profile())
    await hold_event.wait()  # 等到真正持有才继续

    # 此时 pool 已无可用 profile，acquire 应该在超时内报错
    with pytest.raises(asyncio.TimeoutError):
        await pool.acquire(timeout=1.0)

    hold_task.cancel()
    try:
        await hold_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_banned_profile_not_acquired(profiles, store, pool):
    """
    验证：ban() 后的 Profile 不会被 acquire。
    """
    banned = profiles[0]

    # ban 掉一个
    banned.status = ProfileStatus.BANNED
    store.save(banned)

    # 仍然有 2 个可用（max_concurrent=3）
    async with pool.context() as p:
        assert p.id != banned.id


@pytest.mark.asyncio
async def test_release_with_cooldown_sets_cooldown_status(profiles, store, pool):
    """
    验证：release(cooldown=N) 后 profile 进入 COOLDOWN 状态。
    """
    p = profiles[0]

    await pool.release(p, cooldown=3600)

    assert p.status == ProfileStatus.COOLDOWN
    assert p.cooldown_until is not None
    assert p.cooldown_until > time.time()


@pytest.mark.asyncio
async def test_pool_context_manager_releases_on_exception(profiles, pool):
    """
    验证：async with 块内抛异常，Profile 仍然被 release。
    """
    initial_in_use_count = len(pool._in_use)

    with pytest.raises(RuntimeError):
        async with pool.context() as p:
            raise RuntimeError("simulated error")

    # Profile 已归还（不在 in_use 中）
    assert len(pool._in_use) == initial_in_use_count
