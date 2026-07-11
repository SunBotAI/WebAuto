"""
Core/Profile/pool.py — Profile 池（借/还/轮换策略）

并发场景下，多个任务共享 N 个 Profile，通过 acquire/release 借还。
支持策略：round_robin / random / sticky_by_tag / least_used / health_based
"""

from __future__ import annotations

import asyncio
import time
import yaml
from enum import Enum
from pathlib import Path
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
        flush_interval_seconds: float = 5.0,
    ):
        self.store = store
        self.strategy = strategy
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._in_use: Dict[str, float] = {}   # profile_id -> acquire_time
        self._round_robin_index: int = 0
        self._lock = asyncio.Lock()
        self._on_acquire_timeout = on_acquire_timeout
        # ── 内存态脏页追踪 ──────────────────────────────────
        self._dirty: Dict[str, Profile] = {}  # profile_id -> dirty Profile
        self._flush_interval = flush_interval_seconds
        self._flush_task: Optional[asyncio.Task] = None
        self._stop_flush = False
        # pool.yaml 持久化路径（在 store.base_dir 下）
        self._config_path = store.base_dir / "pool.yaml"
        # 健康检测间隔（分钟），0 表示关闭自动检测
        self._health_check_interval: int = 0
        self._load_config()
        # 注册模块级单例
        _set_pool_instance(self)

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
            # 借出前先把脏页刷下去，保证 list_all 能看到最新状态
            await self._flush_dirty()

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
            await self._mark_dirty(profile)

            async with self._lock:
                self._in_use[profile.id] = time.time()

            # 启动定期 flush loop（惰性启动）
            self._ensure_flush_loop()

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
            await self._mark_dirty(profile)
            async with self._lock:
                self._in_use.pop(profile.id, None)
            return

        if cooldown > 0:
            profile.status = ProfileStatus.COOLDOWN
            profile.cooldown_until = time.time() + cooldown
        else:
            profile.status = ProfileStatus.READY

        await self._mark_dirty(profile)

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

    # ─── 脏页追踪 + 定期 flush ─────────────────────────────────

    async def _mark_dirty(self, profile: Profile) -> None:
        """标记 Profile 为脏页（等待定期 flush）"""
        async with self._lock:
            self._dirty[profile.id] = profile

    def _ensure_flush_loop(self) -> None:
        """确保定期 flush loop 正在运行（惰性启动）"""
        if self._flush_task is None or self._flush_task.done():
            self._stop_flush = False
            self._flush_task = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self) -> None:
        """后台定期 flush 所有脏页到磁盘"""
        while not self._stop_flush:
            await asyncio.sleep(self._flush_interval)
            if self._stop_flush:
                break
            await self._flush_dirty()

    async def _flush_dirty(self) -> None:
        """把所有脏页刷到磁盘，然后清空 dirty 集合"""
        async with self._lock:
            dirty_profiles = list(self._dirty.values())
            self._dirty.clear()

        if not dirty_profiles:
            return

        # store.save 是同步的，但非常快（只是写 YAML/JSON），不阻塞事件循环
        for profile in dirty_profiles:
            try:
                self.store.save(profile)
            except Exception:
                # 写失败，把 Profile 塞回 dirty，等下次重试
                async with self._lock:
                    self._dirty[profile.id] = profile
                raise

    async def flush(self) -> None:
        """
        手动触发一次 flush（同步调用）。
        建议在任务开始前 /结束后 /进程退出前调用。
        """
        await self._flush_dirty()

    async def stop(self) -> None:
        """停止 flush loop 并刷最后的脏页（池销毁时调用）"""
        self._stop_flush = True
        await self._flush_dirty()
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

    # ─── 策略/并发数管理（T-090）──────────────────────────────

    def set_strategy(self, strategy: AcquireStrategy) -> None:
        """切换池策略，下次 acquire 即生效，并持久化到 pool.yaml"""
        self.strategy = strategy
        self._save_config()

    def set_max_concurrent(self, max_concurrent: int) -> None:
        """修改最大并发数，实时生效（通过重建 Semaphore 实现），并持久化到 pool.yaml"""
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._save_config()

    def get_status(self) -> dict:
        """返回池状态快照（T-091）"""
        all_profiles = self.store.list_all()
        by_status: Dict[str, int] = {s.value: 0 for s in ProfileStatus}
        for p in all_profiles:
            by_status[p.status.value] = by_status.get(p.status.value, 0) + 1
        return {
            "total": len(all_profiles),
            "ready": by_status.get("ready", 0),
            "running": by_status.get("running", 0),
            "cooldown": by_status.get("cooldown", 0),
            "banned": by_status.get("banned", 0),
            "archived": by_status.get("archived", 0),
            "in_use_ids": list(self._in_use.keys()),
            "strategy": self.strategy.value,
            # max_concurrent 无法从 Semaphore 实时读取，用实例变量记录
            "max_concurrent": self._semaphore._value,  # type: ignore[attr-defined]
            "health_check_interval": self._health_check_interval,
        }

    # ─── pool.yaml 持久化（T-090）─────────────────────────────

    def _save_config(self) -> None:
        """把当前 strategy + max_concurrent + health_check_interval 写 pool.yaml"""
        try:
            data = {
                "strategy": self.strategy.value,
                "max_concurrent": self._semaphore._value,  # type: ignore[attr-defined]
                "health_check_interval": self._health_check_interval,
            }
            tmp = self._config_path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                yaml.dump(data, f)
            tmp.replace(self._config_path)
        except Exception:
            # 持久化失败不影响主流程
            pass

    def _load_config(self) -> None:
        """启动时从 pool.yaml 恢复 strategy + max_concurrent"""
        if not self._config_path.exists():
            return
        try:
            with open(self._config_path) as f:
                data = yaml.safe_load(f)
            if not data:
                return
            if "strategy" in data:
                self.strategy = AcquireStrategy(data["strategy"])
            if "max_concurrent" in data:
                self._semaphore = asyncio.Semaphore(int(data["max_concurrent"]))
            if "health_check_interval" in data:
                self._health_check_interval = int(data["health_check_interval"])
        except Exception:
            # 损坏的 pool.yaml 不阻止启动
            pass

    def set_health_check_interval(self, minutes: int) -> None:
        """设置健康检测间隔（分钟），持久化到 pool.yaml。"""
        self._health_check_interval = max(0, minutes)
        self._save_config()


# ─── 模块级单例（供 proxy_backend 调用）───────────────────────────

_profile_pool_instance: Optional[ProfilePool] = None


def _get_pool_instance() -> Optional[ProfilePool]:
    """返回已创建的 ProfilePool 单例（未创建返回 None）。"""
    return _profile_pool_instance


def _set_pool_instance(pool: ProfilePool) -> None:
    """设置模块级单例（在 ProfilePool 创建处调用）。"""
    global _profile_pool_instance
    _profile_pool_instance = pool
