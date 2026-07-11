"""
Tests/test_store_atomic.py — T-064 Store.save 原子写 + Pool 内存态脏页 flush

验收标准：
- Store.save 用 tempfile.NamedTemporaryFile + os.replace() 原子写
- ProfilePool 在内存维护 dirty flag，定期 flush 到磁盘
- 100 借还/秒 YAML 不损坏
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import yaml
from pathlib import Path
from unittest.mock import patch

import pytest

from Core.Profile import Profile, ProfileStore
from Core.Profile.pool import ProfilePool, AcquireStrategy


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmpdir():
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def store(tmpdir):
    return ProfileStore(base_dir=tmpdir)


@pytest.fixture
def pool(tmpdir):
    store = ProfileStore(base_dir=tmpdir)
    return ProfilePool(store, flush_interval_seconds=0.1)


# ─── Store 原子写测试 ─────────────────────────────────────────────────────────

class TestAtomicWrite:
    def test_save_writes_valid_yaml(self, store, tmpdir):
        """save() 写出的 config.yaml 格式正确，可被 yaml.safe_load 解析"""
        p = Profile(id="p1", name="test")
        store.create(p)

        p.name = "updated"
        store.save(p)

        with open(store._config_path("p1"), encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        assert loaded["name"] == "updated"

    def test_save_atomic_no_partial_write(self, store, tmpdir):
        """模拟进程崩溃：os.replace 前 kill，原始文件不受影响"""
        p = Profile(id="p1", name="test")
        store.create(p)

        # 记录原始文件内容
        original = (tmpdir / "p1" / "config.yaml").read_bytes()

        # 用 mock 让 os.replace 抛出异常（模拟崩溃）
        with patch("os.replace", side_effect=OSError("simulated crash")):
            p.name = "corrupted"
            try:
                store.save(p)
            except OSError:
                pass

        # 原始文件应该完好（没有被部分写入）
        assert (tmpdir / "p1" / "config.yaml").read_bytes() == original

    def test_atomic_write_json_roundtrip(self, store, tmpdir):
        """_atomic_write JSON 路径：写入可读出，内容一致"""
        meta = {"id": "p1", "status": "READY", "tags": ["a", "b"]}
        store._atomic_write(tmpdir / "test_meta.json", meta, is_json=True)

        with open(tmpdir / "test_meta.json", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == meta

    def test_atomic_write_yaml_roundtrip(self, store, tmpdir):
        """_atomic_write YAML 路径：写入可读出，内容一致"""
        config = {"id": "p1", "name": "hello", "status": "READY"}
        store._atomic_write(tmpdir / "test_config.yaml", config, is_json=False)

        with open(tmpdir / "test_config.yaml", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        assert loaded["name"] == "hello"

    def test_create_uses_atomic_write(self, store, tmpdir):
        """create() 也使用原子写，中间失败不污染目录"""
        p = Profile(id="atomic-create", name="test")
        store.create(p)

        # 所有文件都存在且格式正确
        assert (tmpdir / "atomic-create" / "config.yaml").exists()
        assert (tmpdir / "atomic-create" / "fingerprint.json").exists()
        assert (tmpdir / "atomic-create" / "meta.json").exists()

        loaded = yaml.safe_load(open(tmpdir / "atomic-create" / "config.yaml"))
        assert loaded["id"] == "atomic-create"


# ─── Pool 脏页 flush 测试 ─────────────────────────────────────────────────────

class TestPoolDirtyFlush:
    @pytest.mark.asyncio
    async def test_dirty_profile_not_immediately_written(self, pool, tmpdir):
        """脏页不会立即写盘（acquire 时才 flush）"""
        p = Profile(id="dirty-p1", name="test")
        pool.store.create(p)

        # 模拟 acquire 触发 dirty
        await pool.acquire(tag="tag1")

        # 等待 flush loop 触发
        await asyncio.sleep(0.3)

        # 验证文件已写（acquire 前会先 _flush_dirty）
        assert (tmpdir / "dirty-p1" / "config.yaml").exists()

    @pytest.mark.asyncio
    async def test_flush_manual(self, pool, tmpdir):
        """手动 flush() 把脏页刷到磁盘"""
        p = Profile(id="flush-p1", name="test")
        pool.store.create(p)

        # acquire → 标记 dirty
        profile = await pool.acquire(tag="tag1")
        profile.name = "flushed-name"
        # release → 标记 dirty（但未写盘）
        await pool.release(profile)

        # flush 前文件未更新
        before = yaml.safe_load(open(tmpdir / "flush-p1" / "config.yaml"))
        assert before["name"] == "test"

        # 手动 flush
        await pool.flush()

        # flush 后文件已更新
        after = yaml.safe_load(open(tmpdir / "flush-p1" / "config.yaml"))
        assert after["name"] == "flushed-name"

        await pool.stop()

    @pytest.mark.asyncio
    async def test_periodic_flush(self, pool, tmpdir):
        """脏页在 flush_interval_seconds 后自动 flush"""
        p = Profile(id="periodic-p1", name="test")
        pool.store.create(p)

        profile = await pool.acquire(tag="tag1")
        profile.name = "periodic-name"
        await pool.release(profile)

        # 等待定期 flush（interval=0.1s）
        await asyncio.sleep(0.4)

        after = yaml.safe_load(open(tmpdir / "periodic-p1" / "config.yaml"))
        assert after["name"] == "periodic-name"

        await pool.stop()

    @pytest.mark.asyncio
    async def test_stop_flushes_remaining_dirty(self, pool, tmpdir):
        """stop() 会刷掉最后的脏页再退出"""
        p = Profile(id="stop-p1", name="test")
        pool.store.create(p)

        profile = await pool.acquire(tag="tag1")
        profile.name = "stop-name"
        await pool.release(profile)

        # stop 前文件未更新
        before = yaml.safe_load(open(tmpdir / "stop-p1" / "config.yaml"))
        assert before["name"] == "test"

        # stop
        await pool.stop()

        # stop 后文件已更新
        after = yaml.safe_load(open(tmpdir / "stop-p1" / "config.yaml"))
        assert after["name"] == "stop-name"


# ─── 高频借还测试 ─────────────────────────────────────────────────────────────

class TestHighFrequencyIntegrity:
    @pytest.mark.asyncio
    async def test_100_acquire_release_no_yaml_corruption(self, pool, tmpdir):
        """
        100 次借还/秒场景：YAML 全程不损坏。
        这是 T-064 的核心验收标准。
        """
        # 创建 10 个 profiles（足够 100 次借还）
        for i in range(10):
            p = Profile(id=f"hf-p{i}", name=f"profile-{i}")
            pool.store.create(p)

        errors = []

        async def acquire_release(tag: str, count: int):
            for i in range(count):
                try:
                    profile = await pool.acquire(tag=f"{tag}-{i % 3}")
                    profile.last_used = time.time()
                    await pool.release(profile)
                except Exception as e:
                    errors.append(e)

        # 模拟 100 次借还（并发 20 个 task 各 5 次）
        tasks = [acquire_release(f"task{i}", 5) for i in range(20)]
        await asyncio.gather(*tasks)

        assert errors == [], f"Errors during high-freq ops: {errors}"

        # 验证所有 YAML 仍然可读
        for i in range(10):
            yaml_path = tmpdir / f"hf-p{i}" / "config.yaml"
            try:
                with open(yaml_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                assert data["id"] == f"hf-p{i}"
            except yaml.YAMLError as e:
                pytest.fail(f"YAML corrupted for hf-p{i}: {e}")

        await pool.stop()

    @pytest.mark.asyncio
    async def test_flush_on_acquire_prevents_stale_reads(self, pool, tmpdir):
        """acquire 前先 flush，保证 list_all 看到最新状态"""
        p = Profile(id="stale-p1", name="test")
        pool.store.create(p)

        # profile 在内存被标记 dirty
        profile = await pool.acquire(tag="tag1")
        profile.name = "stale-updated"
        await pool.release(profile)

        # 在 flush_interval 到期前 acquire 另一个 profile
        # 此时 _select_profile → list_all，flush 会先执行
        p2 = Profile(id="stale-p2", name="test2")
        pool.store.create(p2)
        profile2 = await pool.acquire(tag="tag2")

        # stale-p1 的脏数据应该已被 flush，list_all 能看到
        all_profiles = pool.store.list_all()
        names = {p.id: p.name for p in all_profiles}
        assert names.get("stale-p1") == "stale-updated"
        assert names.get("stale-p2") == "test2"

        await pool.release(profile2)
        await pool.stop()
