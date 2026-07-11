"""
Tools/service_registry.py — T-073 全局单例注册中心（线程安全）

给 Web/MCP 共享的全局单例：
    ProfileStore / ProfilePool / ProxyRotator / ProxyPolicy

线程安全：所有操作走 threading.RLock（多线程 Playwright/CDP 场景需要）。

用法：
    from Tools.service_registry import (
        get_store, get_pool, get_rotator,
        register_service, lifecycle,
        configure_pool, configure_rotator,
    )

    # 初始化（通常只做一次）
    store = get_store(base_dir=Path("./data/profiles"))
    pool  = get_pool(base_dir=Path("./data/profiles"))
    rotator = get_rotator()

    # 在 async with lifecycle() 里运行（自动启动/停止 flush loop）
    async with lifecycle():
        profile = await pool.acquire()
        ...

    # Pool 配置（可在任意时刻调用）
    configure_pool(strategy="round_robin", max_concurrent=5)
    configure_rotator(max_failures=5, cooldown_minutes=15)
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Callable, Any

from Core.Profile import ProfileStore, ProfilePool, AcquireStrategy
from Core.Profile.proxy_rotator import ProxyRotator, ProxyPolicy


# ─── 全局状态（线程安全单例）────────────────────────────────────────────────

_registry_lock = threading.RLock()

_store: Optional[ProfileStore] = None
_pool: Optional[ProfilePool] = None
_rotator: Optional[ProxyRotator] = None
_policy: Optional[ProxyPolicy] = None


# ─── 初始化函数 ─────────────────────────────────────────────────────────────

def get_store(base_dir: Optional[Path] = None) -> ProfileStore:
    """
    获取 ProfileStore 单例（惰性创建，线程安全）。

    Args:
        base_dir: Profile 数据目录，不传则用默认路径。
                  首次调用后再次传入不同路径会被忽略。
    """
    global _store
    with _registry_lock:
        if _store is None:
            _store = ProfileStore(base_dir=base_dir or Path("./data/profiles"))
        return _store


def get_pool(
    base_dir: Optional[Path] = None,
    strategy: AcquireStrategy = AcquireStrategy.LEAST_USED,
    max_concurrent: int = 10,
) -> ProfilePool:
    """
    获取 ProfilePool 单例（惰性创建，线程安全）。

    Args:
        base_dir: Profile 数据目录。
        strategy: 池策略（首次调用后被 configure_pool 覆盖，不影响已有 pool）。
        max_concurrent: 最大并发（首次调用后被 configure_pool 覆盖）。
    """
    global _pool
    with _registry_lock:
        if _pool is None:
            _pool = ProfilePool(
                get_store(base_dir=base_dir),
                strategy=strategy,
                max_concurrent=max_concurrent,
            )
        return _pool


def get_rotator(
    policy: Optional[ProxyPolicy] = None,
    max_failures: int = 3,
    cooldown_minutes: float = 30.0,
) -> ProxyRotator:
    """
    获取 ProxyRotator 单例（惰性创建，线程安全）。

    Args:
        policy: 传入 ProxyPolicy 实例（优先使用）。
        max_failures: 默认值（policy 为 None 时使用）。
        cooldown_minutes: 默认值（policy 为 None 时使用）。
    """
    global _rotator, _policy
    with _registry_lock:
        if _rotator is None:
            _policy = policy or ProxyPolicy(
                max_failures=max_failures,
                cooldown_minutes=cooldown_minutes,
            )
            _rotator = ProxyRotator(policy=_policy)
        return _rotator


# ─── 配置函数（T-073 扩展）──────────────────────────────────────────────────

def configure_pool(
    strategy: Optional[str] = None,
    max_concurrent: Optional[int] = None,
) -> None:
    """
    运行时配置 Pool 参数（实时生效 + 持久化）。

    Args:
        strategy: "round_robin" | "random" | "sticky_by_tag" | "least_used" | "health_based"
        max_concurrent: 并发数，必须 >= 1
    """
    pool = get_pool()
    if strategy is not None:
        pool.set_strategy(AcquireStrategy(strategy))
    if max_concurrent is not None:
        pool.set_max_concurrent(max_concurrent)


def configure_rotator(
    max_failures: Optional[int] = None,
    cooldown_minutes: Optional[float] = None,
) -> None:
    """
    运行时配置 ProxyPolicy 参数。

    注意：已创建的 ProxyRotator 持有旧 policy，不影响正在追踪的 Profile；
    新注册的 Profile 使用更新后的 policy。
    """
    global _policy, _rotator
    with _registry_lock:
        if _policy is None:
            _policy = ProxyPolicy()
        if max_failures is not None:
            _policy.max_failures = max_failures
        if cooldown_minutes is not None:
            _policy.cooldown_minutes = cooldown_minutes


# ─── 生命周期（T-093）────────────────────────────────────────────────────────

@asynccontextmanager
async def lifecycle(base_dir: Optional[Path] = None):
    """
    Async context manager：进入时建 Pool + 启动 flush task，退出时 flush + stop。

    用法：
        store = get_store(Path("./data/profiles"))
        pool  = get_pool(Path("./data/profiles"))
        rotator = get_rotator()

        async with lifecycle():
            profile = await pool.acquire(tag="my-task")
            try:
                await do_work(profile)
            finally:
                await pool.release(profile)

    退出时自动：
        1. 停止 flush loop（不再接收新 dirty）
        2. 把所有剩余 dirty 页 flush 到磁盘
        3. 同步所有 Profile YAML
    """
    pool = get_pool(base_dir=base_dir)
    # 确保 flush loop 在运行
    pool._ensure_flush_loop()
    try:
        yield pool
    finally:
        # 退出时 flush 剩余脏页 + 停止 loop
        await pool.stop()


# ─── 测试支持 ───────────────────────────────────────────────────────────────

def _reset_for_test() -> None:
    """测试用：重置所有单例（必须在 import 前或 isolated 环境里用）"""
    global _store, _pool, _rotator, _policy
    with _registry_lock:
        _store = None
        _pool = None
        _rotator = None
        _policy = None
