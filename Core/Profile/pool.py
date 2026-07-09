"""
Core/Profile/pool.py — Profile 池（借/还/轮换策略）

并发场景下，多个任务共享 N 个 Profile，通过 acquire/release 借还。
支持策略：round_robin / random / sticky_by_tag / least_used / health_based
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Optional, Dict, List
from contextlib import asynccontextmanager

from .profile import Profile, ProfileStatus
from .store import ProfileStore


class AcquireStrategy(Enum):
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    STICKY_BY_TAG = "sticky_by_tag"   # 同一任务用同一 Profile
    LEAST_USED = "least_used"
    HEALTH_BASED = "health_based"     # 优先选 cooldown 已结束的


class ProfilePool:
    """
    并发场景下借/还 Profile 的池子。

    典型用法:
        pool = ProfilePool(store, strategy=AcquireStrategy.LEAST_USED, max_concurrent=5)
        async with pool.context(tag="grab-task") as profile:
            # use profile
    """

    def __init__(
        self,
        store: ProfileStore,
        *,
        strategy: AcquireStrategy = AcquireStrategy.LEAST_USED,
        max_concurrent: int = 10,
        on_acquire_timeout: float = 30.0,
    ):
        self.store = store
        self.strategy = strategy
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._in_use: Dict[str, float] = {}   # profile_id -> acquire_time
        self._round_robin_index: int = 0
        self._lock = asyncio.Lock()
        self._on_acquire_timeout = on_acquire_timeout

    # ─── 核心 acquire/release ──────────────────────────────────

    async def acquire(
        self,
        *,
        tag: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Profile:
        """
        异步借一个 Profile。

        Args:
            tag: 用于 sticky_by_tag 策略（同一 tag 总是返回同一个 Profile）
            timeout: 借不到则超时（秒）

        Returns:
            Profile 实例（已标记为 RUNNING）

        Raises:
            asyncio.TimeoutError: 等待超时
        """
        timeout = timeout or self._on_acquire_timeout

        deadline = time.monotonic() + timeout

        async with self._semaphore:
            while True:
                profile = await self._select_profile(tag=tag)
                if profile is not None:
                    break
                # 没可用的，等待 cooldown 变化或被唤醒（重试）
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError(
                        f"No available profile for tag={tag} after {timeout}s"
                    )
                # 等一小段时间再重试（避免 busy loop）
                await asyncio.sleep(min(0.1, remaining))

            profile.status = ProfileStatus.RUNNING
            profile.last_used = time.time()
            self.store.save(profile)

            async with self._lock:
                self._in_use[profile.id] = time.time()

            return profile

    async def release(self, profile: Profile, *, cooldown: float = 0) -> None:
        """
        归还 Profile。

        Args:
            profile: 借出的 Profile
            cooldown: 归还后冷却时间（秒），防风控

        Note:
            如果 profile 在持有期间被 ban() / archive()，status 会被设为 BANNED / ARCHIVED。
            release() 不应覆盖这些终态，只对 READY / RUNNING / COOLDOWN 的 profile 正常操作。
        """
        profile.last_used = time.time()

        # 不覆盖终态：BAN 和 ARCHIVED 保持不变
        if profile.status in (ProfileStatus.BANNED, ProfileStatus.ARCHIVED):
            self.store.save(profile)
            async with self._lock:
                self._in_use.pop(profile.id, None)
            return

        if cooldown > 0:
            profile.status = ProfileStatus.COOLDOWN
            profile.cooldown_until = time.time() + cooldown
        else:
            profile.status = ProfileStatus.READY

        self.store.save(profile)

        async with self._lock:
            self._in_use.pop(profile.id, None)

    @asynccontextmanager
    async def context(self, **kwargs):
        """
        上下文管理器，用法:

            async with pool.context(tag="grab") as profile:
                # use profile
        """
        p = await self.acquire(**kwargs)
        try:
            yield p
        finally:
            await self.release(p)

    # ─── 策略选择 ──────────────────────────────────────────────

    async def _select_profile(self, tag: Optional[str] = None) -> Optional[Profile]:
        """根据策略从可用 Profile 中选一个"""
        all_profiles = self.store.list_all()
        available = [p for p in all_profiles if self._is_available(p)]

        if not available:
            return None

        if self.strategy == AcquireStrategy.RANDOM:
            import random
            return random.choice(available)

        elif self.strategy == AcquireStrategy.LEAST_USED:
            # 选 last_used 最旧的
            return min(available, key=lambda p: p.last_used or 0)

        elif self.strategy == AcquireStrategy.ROUND_ROBIN:
            async with self._lock:
                idx = self._round_robin_index % len(available)
                self._round_robin_index += 1
            return available[idx]

        elif self.strategy == AcquireStrategy.HEALTH_BASED:
            # 优先选 READY 的，其次选 cooldown 已结束的
            ready = [p for p in available if p.status == ProfileStatus.READY]
            if ready:
                return min(ready, key=lambda p: p.last_used or 0)
            # cooldown 已过
            now = time.time()
            cooling = [p for p in available
                       if p.status == ProfileStatus.COOLDOWN
                       and p.cooldown_until is not None
                       and now >= p.cooldown_until]
            if cooling:
                selected = min(cooling, key=lambda p: p.cooldown_until)
                selected.status = ProfileStatus.READY
                return selected
            return None

        elif self.strategy == AcquireStrategy.STICKY_BY_TAG:
            # tag 绑定：记录 tag → profile_id 映射（内存态，重启丢失）
            if not hasattr(self, "_tag_map"):
                self._tag_map: Dict[str, str] = {}
            cached_id = self._tag_map.get(tag or "")
            if cached_id:
                for p in available:
                    if p.id == cached_id:
                        return p
            # 无缓存，选一个并记录
            selected = min(available, key=lambda p: p.last_used or 0)
            if tag:
                self._tag_map[tag] = selected.id
            return selected

        return available[0]

    def _is_available(self, profile: Profile) -> bool:
        """Profile 是否可借"""
        if profile.id in self._in_use:
            return False
        if profile.status == ProfileStatus.BANNED:
            return False
        if profile.status == ProfileStatus.ARCHIVED:
            return False
        if profile.status == ProfileStatus.RUNNING:
            return False
        if profile.is_cooldown_active():
            return False
        return True
