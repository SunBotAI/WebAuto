"""
Tests/test_profile_ban_archive.py — T-066 Profile ban() / archive() / restore() 测试

验证：
1. ban() 标记 BANNED + 持久化，acquire 拒绝
2. archive() 标记 ARCHIVED + 持久化，list_active 不出现
3. restore() 恢复 BANNED/ARCHIVED → READY
4. restore() 对 READY 状态抛 ValueError
5. 序列化/反序列化保留 ban/archive 状态
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from Core.Profile import Profile, ProfileStatus
from Core.Profile.store import ProfileStore
from Core.Profile.pool import ProfilePool, AcquireStrategy


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return ProfileStore(base_dir=tmp_path)


@pytest.fixture
def profile_banned(tmp_path, store):
    """持久化的 BANNED profile"""
    p = Profile(id="banned-001", name="Banned Profile")
    store.create(p)
    p.ban(store=store)
    return p


@pytest.fixture
def profile_archived(tmp_path, store):
    """持久化的 ARCHIVED profile"""
    p = Profile(id="archived-001", name="Archived Profile")
    store.create(p)
    p.archive(store=store)
    return p


@pytest.fixture
def profile_ready(tmp_path, store):
    """正常的 READY profile"""
    p = Profile(id="ready-001", name="Ready Profile")
    p.fingerprint.locale = "en-US"
    p.fingerprint.timezone = "America/New_York"
    p.fingerprint.screen_resolution = (1920, 1080)
    store.create(p)
    return p


# ─── Test: ban() ─────────────────────────────────────────────────────────────

def test_ban_sets_status_and_persists(tmp_path, store):
    """ban() 标记 BANNED 并持久化到 meta.json"""
    p = Profile(id="ban-test-1", name="Ban Test")
    store.create(p)
    assert p.status == ProfileStatus.READY

    p.ban(store=store)

    assert p.status == ProfileStatus.BANNED
    # 持久化验证：重新加载后状态保留
    reloaded = store.get("ban-test-1")
    assert reloaded.status == ProfileStatus.BANNED


def test_ban_on_new_profile_without_store(tmp_path):
    """ban() 在未持久化（无 storage_dir）时只改内存状态"""
    p = Profile(id="ban-nostore", name="Ban No Store")
    # storage_dir 为 None 时 ban() 不抛异常
    p.ban()
    assert p.status == ProfileStatus.BANNED


def test_ban_preserves_other_fields(tmp_path, store):
    """ban() 只改 status，不影响其他字段"""
    p = Profile(id="ban-fields", name="Ban Fields Test")
    p.tags = ["tag1", "tag2"]
    p.fingerprint.locale = "zh-CN"
    store.create(p)

    p.ban(store=store)

    assert p.name == "Ban Fields Test"
    assert p.tags == ["tag1", "tag2"]
    assert p.fingerprint.locale == "zh-CN"
    reloaded = store.get("ban-fields")
    assert reloaded.name == "Ban Fields Test"
    assert reloaded.tags == ["tag1", "tag2"]


# ─── Test: archive() ─────────────────────────────────────────────────────────

def test_archive_sets_status_and_persists(tmp_path, store):
    """archive() 标记 ARCHIVED 并持久化"""
    p = Profile(id="archive-test-1", name="Archive Test")
    store.create(p)
    assert p.status == ProfileStatus.READY

    p.archive(store=store)

    assert p.status == ProfileStatus.ARCHIVED
    reloaded = store.get("archive-test-1")
    assert reloaded.status == ProfileStatus.ARCHIVED


def test_archive_on_new_profile_without_store():
    """archive() 在未持久化时只改内存状态"""
    p = Profile(id="archive-nostore", name="Archive No Store")
    p.archive()
    assert p.status == ProfileStatus.ARCHIVED


def test_archive_preserves_storage_dir(tmp_path, store):
    """archive() 不删除 storage_dir"""
    p = Profile(id="archive-storage", name="Archive Storage Test")
    store.create(p)
    storage = p.storage_dir

    p.archive(store=store)

    assert storage.exists()
    assert (storage / "meta.json").exists()
    reloaded = store.get("archive-storage")
    assert reloaded.storage_dir == storage


# ─── Test: restore() ─────────────────────────────────────────────────────────

def test_restore_banned_to_ready(tmp_path, store):
    """restore() 将 BANNED 恢复为 READY"""
    p = Profile(id="restore-ban", name="Restore Banned")
    store.create(p)
    p.ban(store=store)

    p.restore(store=store)

    assert p.status == ProfileStatus.READY
    reloaded = store.get("restore-ban")
    assert reloaded.status == ProfileStatus.READY


def test_restore_archived_to_ready(tmp_path, store):
    """restore() 将 ARCHIVED 恢复为 READY"""
    p = Profile(id="restore-arc", name="Restore Archived")
    store.create(p)
    p.archive(store=store)

    p.restore(store=store)

    assert p.status == ProfileStatus.READY
    reloaded = store.get("restore-arc")
    assert reloaded.status == ProfileStatus.READY


def test_restore_ready_raises(tmp_path, store):
    """restore() 对 READY 状态抛 ValueError"""
    p = Profile(id="restore-ready", name="Restore Ready")
    store.create(p)

    with pytest.raises(ValueError, match="not banned/archived"):
        p.restore()


def test_restore_cooldown_raises(tmp_path, store):
    """restore() 对 COOLDOWN 状态抛 ValueError"""
    p = Profile(id="restore-cool", name="Restore Cooldown")
    store.create(p)
    p.status = ProfileStatus.COOLDOWN
    p.cooldown_until = time.time() + 3600
    store.save(p)

    with pytest.raises(ValueError, match="not banned/archived"):
        p.restore()


def test_restore_running_raises(tmp_path, store):
    """restore() 对 RUNNING 状态抛 ValueError"""
    p = Profile(id="restore-run", name="Restore Running")
    store.create(p)
    p.status = ProfileStatus.RUNNING
    store.save(p)

    with pytest.raises(ValueError, match="not banned/archived"):
        p.restore()


# ─── Test: Pool 拒绝 BANNED / ARCHIVED ──────────────────────────────────────

@pytest.mark.asyncio
async def test_pool_acquire_rejects_banned(store, profile_banned, profile_ready):
    """acquire() 拒绝 BANNED profile，只返回 READY"""
    pool = ProfilePool(store, strategy=AcquireStrategy.ROUND_ROBIN, max_concurrent=10)

    # BANNED 不应该被借到
    acquired = await pool.acquire(timeout=1.0)
    assert acquired.id == profile_ready.id
    assert acquired.status == ProfileStatus.RUNNING


@pytest.mark.asyncio
async def test_pool_acquire_rejects_archived(store, profile_archived, profile_ready):
    """acquire() 拒绝 ARCHIVED profile，只返回 READY"""
    pool = ProfilePool(store, strategy=AcquireStrategy.ROUND_ROBIN, max_concurrent=10)

    acquired = await pool.acquire(timeout=1.0)
    assert acquired.id == profile_ready.id


@pytest.mark.asyncio
async def test_pool_acquire_rejects_all_banned_archived(store, profile_banned, profile_archived):
    """所有 profile 都被 ban/archive 时 acquire 抛 TimeoutError"""
    pool = ProfilePool(store, strategy=AcquireStrategy.ROUND_ROBIN, max_concurrent=10)

    with pytest.raises(asyncio.TimeoutError):
        await pool.acquire(timeout=0.5)


@pytest.mark.asyncio
async def test_restore_then_acquire_ok(store, profile_banned):
    """restore() 后 profile 可重新被 acquire"""
    pool = ProfilePool(store, strategy=AcquireStrategy.ROUND_ROBIN, max_concurrent=10)

    # 先 ban
    p = store.get("banned-001")
    assert p.status == ProfileStatus.BANNED

    # 恢复
    p.restore(store=store)
    assert p.status == ProfileStatus.READY

    # 现在可以借到
    acquired = await pool.acquire(timeout=1.0)
    assert acquired.id == "banned-001"


# ─── Test: store.list_active() 排除 BANNED / ARCHIVED ───────────────────────

def test_list_active_excludes_banned(store, profile_banned, profile_ready):
    """list_all() 中过滤非 BANNED/ARCHIVED 时不返回 BANNED profile"""
    all_profiles = store.list_all()
    active = [p for p in all_profiles if p.status not in (ProfileStatus.BANNED, ProfileStatus.ARCHIVED)]
    ids = [p.id for p in active]
    assert "banned-001" not in ids
    assert "ready-001" in ids


def test_list_active_excludes_archived(store, profile_archived, profile_ready):
    """list_all() 中过滤非 BANNED/ARCHIVED 时不返回 ARCHIVED profile"""
    all_profiles = store.list_all()
    active = [p for p in all_profiles if p.status not in (ProfileStatus.BANNED, ProfileStatus.ARCHIVED)]
    ids = [p.id for p in active]
    assert "archived-001" not in ids
    assert "ready-001" in ids


def test_list_all_includes_banned_archived(store, profile_banned, profile_archived, profile_ready):
    """list_all() 返回包括 BANNED 和 ARCHIVED 的所有 profile"""
    all_profiles = store.list_all()
    ids = [p.id for p in all_profiles]
    assert "banned-001" in ids
    assert "archived-001" in ids
    assert "ready-001" in ids


# ─── Test: 序列化/反序列化保留 ban/archive 状态 ─────────────────────────────

def test_to_dict_from_dict_preserves_banned(store, profile_banned):
    """to_dict() / from_dict() 保留 BANNED 状态"""
    data = profile_banned.to_dict()
    assert data["status"] == "banned"

    p2 = Profile.from_dict(data)
    assert p2.status == ProfileStatus.BANNED


def test_to_dict_from_dict_preserves_archived(store, profile_archived):
    """to_dict() / from_dict() 保留 ARCHIVED 状态"""
    data = profile_archived.to_dict()
    assert data["status"] == "archived"

    p2 = Profile.from_dict(data)
    assert p2.status == ProfileStatus.ARCHIVED


# ─── Test: ban() + release() 生命周期 ───────────────────────────────────────

@pytest.mark.asyncio
async def test_ban_while_held_then_release(tmp_path, store):
    """在 pool 外对正在 RUNNING 的 profile ban，然后 release"""
    p = Profile(id="ban-while-held", name="Ban While Held")
    p.fingerprint.locale = "en-US"
    p.fingerprint.timezone = "America/New_York"
    p.fingerprint.screen_resolution = (1920, 1080)
    store.create(p)

    pool = ProfilePool(store, strategy=AcquireStrategy.ROUND_ROBIN, max_concurrent=10)

    # 借出
    acquired = await pool.acquire(timeout=1.0)
    assert acquired.id == "ban-while-held"
    assert acquired.status == ProfileStatus.RUNNING

    # 持有期间 ban（模拟风控检测到封号）
    acquired.ban(store=store)
    assert acquired.status == ProfileStatus.BANNED

    # 释放回 pool
    await pool.release(acquired)

    # 下次 acquire 不会再借到这个 BANNED profile
    all_profiles = store.list_all()
    active = [p for p in all_profiles if p.status not in (ProfileStatus.BANNED, ProfileStatus.ARCHIVED)]
    ids = [p.id for p in active]
    assert "ban-while-held" not in ids
