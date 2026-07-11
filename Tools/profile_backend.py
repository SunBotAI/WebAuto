"""
Tools/profile_backend.py — T-071 Profile CRUD + warmup + import/export 纯函数

对外暴露的纯函数（无状态 / 全局单例）：
    list_profiles()         → List[Profile]
    get_profile(id)        → Profile | None
    create_profile(data)   → Profile
    update_profile(id, data) → Profile | None
    delete_profile(id)     → bool
    warmup_profile(id)     → Profile | None
    export_profile(id)     → dict | None
    import_profile(data)   → Profile

内部单例（惰性创建）：
    _pool: ProfilePool
    _store: ProfileStore

导出 Pool 状态管理（T-090 / T-091）：
    set_pool_strategy(strategy: str)   → None
    set_pool_max_concurrent(n: int)     → None
    get_pool_status()                   → dict
    uncooldown_profile(id)              → bool
    flush_pool()                        → None
    stop_pool()                         → None
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

from Core.Profile import Profile, ProfileStore, ProfileStatus, AcquireStrategy
from Core.Profile.pool import ProfilePool


# ─── 单例（惰性初始化）────────────────────────────────────────────────────────

_pool: Optional[ProfilePool] = None
_store: Optional[ProfileStore] = None


def _get_store(base_dir: Optional[Path] = None) -> ProfileStore:
    global _store
    if _store is None:
        _store = ProfileStore(base_dir=base_dir or Path("./data/profiles"))
    return _store


def _get_pool(
    base_dir: Optional[Path] = None,
    strategy: AcquireStrategy = AcquireStrategy.LEAST_USED,
    max_concurrent: int = 10,
) -> ProfilePool:
    global _pool
    if _pool is None:
        _pool = ProfilePool(_get_store(base_dir), strategy=strategy, max_concurrent=max_concurrent)
    return _pool


# ─── CRUD 纯函数 ─────────────────────────────────────────────────────────────

def list_profiles() -> List[Profile]:
    """返回所有 Profile"""
    return _get_store().list_all()


def get_profile(profile_id: str) -> Optional[Profile]:
    """根据 id 查单个 Profile，不存在返回 None"""
    store = _get_store()
    all_profiles = store.list_all()
    for p in all_profiles:
        if p.id == profile_id:
            return p
    return None


def create_profile(data: Dict[str, Any]) -> Profile:
    """
    创建新 Profile。

    Args:
        data: dict，会透传给 Profile.from_dict()
            至少包含 id 或自动生成 UUID
            至少包含 name

    Returns:
        创建好的 Profile

    Raises:
        ValueError: id 冲突（已存在）
    """
    store = _get_store()
    existing = get_profile(data.get("id", ""))
    if existing is not None:
        raise ValueError(f"Profile with id={existing.id} already exists")

    # 构造 Profile（走 from_dict）
    profile = Profile.from_dict(dict(data))
    store.create(profile)
    return profile


def update_profile(profile_id: str, data: Dict[str, Any]) -> Optional[Profile]:
    """
    更新已有 Profile。

    Args:
        profile_id: 要更新的 Profile id
        data: dict，keys 会被合并到现有 Profile（via from_dict 再 patch）

    Returns:
        更新后的 Profile，不存在返回 None
    """
    store = _get_store()
    existing = get_profile(profile_id)
    if existing is None:
        return None

    # 合并：现有值 + 新值（from_dict 处理）
    merged = existing.to_dict()
    merged.update(data)
    # from_dict 会过滤未知字段 + 处理 status 枚举
    updated = Profile.from_dict(merged)
    updated.id = profile_id  # 不允许改 id
    store.save(updated)
    return updated


def delete_profile(profile_id: str) -> bool:
    """
    删除 Profile（物理删除目录）。

    Returns:
        True 删了，False 找不到
    """
    store = _get_store()
    existing = get_profile(profile_id)
    if existing is None:
        return False
    store.delete(profile_id)
    return True


def warmup_profile(profile_id: str) -> Optional[Profile]:
    """
    预热 Profile（触发一次 acquire + release，走完全部初始化流程）。

    Returns:
        预热后的 Profile，id 不存在返回 None
    """
    profile = get_profile(profile_id)
    if profile is None:
        return None

    pool = _get_pool()
    # 同步调用（asyncio.run），避免侵入调用方
    async def _warmup():
        p = await pool.acquire(tag=f"warmup-{profile_id}", timeout=5.0)
        await pool.release(p)
        return p

    try:
        warmed = asyncio.run(_warmup())
        # warmup 后刷新 store 里的副本
        return get_profile(profile_id)
    except (asyncio.TimeoutError, Exception):
        return get_profile(profile_id)


# ─── import / export ──────────────────────────────────────────────────────────

def export_profile(profile_id: str) -> Optional[dict]:
    """
    导出单个 Profile 为可 JSON 序列化的 dict（不含 storage_dir 等运行时字段）。

    Returns:
        dict，失败返回 None
    """
    profile = get_profile(profile_id)
    if profile is None:
        return None
    data = profile.to_dict()
    # storage_dir 是运行时 Path，不应导出
    data.pop("storage_dir", None)
    return data


def import_profile(data: Dict[str, Any]) -> Profile:
    """
    导入 Profile dict（JSON 导入场景）。

    id 冲突 → 覆盖（upsert）。
    无 id → 自动生成。

    Returns:
        导入后的 Profile
    """
    if "id" not in data or not data["id"]:
        # 自动生成 id
        import uuid
        data["id"] = str(uuid.uuid4())[:8]

    existing = get_profile(data["id"])
    if existing is not None:
        # upsert：全量替换
        store = _get_store()
        updated = Profile.from_dict(dict(data))
        updated.id = existing.id  # 不允许改 id
        store.save(updated)
        return updated
    else:
        return create_profile(data)


# ─── Pool 状态管理（T-090 / T-091）───────────────────────────────────────────

def set_pool_strategy(strategy: str) -> None:
    """
    切换池策略。

    Args:
        strategy: "round_robin" | "random" | "sticky_by_tag" | "least_used" | "health_based"
    """
    pool = _get_pool()
    pool.set_strategy(AcquireStrategy(strategy))


def set_pool_max_concurrent(n: int) -> None:
    """
    修改最大并发数。

    Args:
        n: 并发数，必须 >= 1
    """
    pool = _get_pool()
    pool.set_max_concurrent(n)


def get_pool_status() -> dict:
    """返回池状态快照"""
    pool = _get_pool()
    return pool.get_status()


def uncooldown_profile(profile_id: str) -> bool:
    """
    解除 Profile 的 cooldown 状态（改为 READY，清除 cooldown_until）。

    Returns:
        True 成功，False 找不到
    """
    profile = get_profile(profile_id)
    if profile is None:
        return False
    if profile.status != ProfileStatus.COOLDOWN:
        return False
    profile.uncooldown()
    _get_store().save(profile)
    return True


def flush_pool() -> None:
    """手动 flush 脏页到磁盘"""
    async def _flush():
        pool = _get_pool()
        await pool.flush()
    asyncio.run(_flush())


def stop_pool() -> None:
    """停止池（flush 剩余脏页，取消 flush loop）"""
    async def _stop():
        pool = _get_pool()
        await pool.stop()
    asyncio.run(_stop())
