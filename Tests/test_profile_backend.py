"""
Tests/test_profile_backend.py — T-071 Profile backend 纯函数单测

覆盖：list / get / create / update / delete / warmup / import / export
"""

from __future__ import annotations

import pytest
import shutil
import tempfile
from pathlib import Path

from Core.Profile import Profile, ProfileStatus
from Tools import profile_backend as pb


# ─── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """每个测试用独立目录，重置单例"""
    # 重置单例
    import Tools.profile_backend as mod
    mod._pool = None
    mod._store = None
    # 注入测试目录
    monkeypatch.setattr(mod, "_get_store", lambda base_dir=None: mod.ProfileStore(base_dir=tmp_path))
    monkeypatch.setattr(mod, "_get_pool", lambda **kw: mod.ProfilePool(mod._get_store(), **kw))
    yield tmp_path
    # cleanup
    try:
        mod._pool = None
        mod._store = None
    except Exception:
        pass


# ─── list_profiles ─────────────────────────────────────────────────────────────

class TestListProfiles:
    def test_list_empty(self):
        assert pb.list_profiles() == []

    def test_list_returns_created(self):
        p1 = pb.create_profile({"id": "list-p1", "name": "P1"})
        p2 = pb.create_profile({"id": "list-p2", "name": "P2"})
        ids = [p.id for p in pb.list_profiles()]
        assert "list-p1" in ids
        assert "list-p2" in ids


# ─── get_profile ─────────────────────────────────────────────────────────────

class TestGetProfile:
    def test_get_missing_returns_none(self):
        assert pb.get_profile("nonexistent") is None

    def test_get_existing(self):
        created = pb.create_profile({"id": "get-p1", "name": "GetTest"})
        fetched = pb.get_profile("get-p1")
        assert fetched is not None
        assert fetched.id == "get-p1"
        assert fetched.name == "GetTest"


# ─── create_profile ─────────────────────────────────────────────────────────

class TestCreateProfile:
    def test_create_with_id(self):
        p = pb.create_profile({"id": "create-p1", "name": "Created"})
        assert p.id == "create-p1"
        assert p.name == "Created"
        assert p.status == ProfileStatus.READY

    def test_create_without_id_generates_uuid(self):
        p = pb.create_profile({"name": "Auto"})
        assert p.id != ""
        assert len(p.id) == 8

    def test_create_duplicate_id_raises(self):
        pb.create_profile({"id": "dup-id", "name": "First"})
        with pytest.raises(ValueError, match="already exists"):
            pb.create_profile({"id": "dup-id", "name": "Second"})


# ─── update_profile ─────────────────────────────────────────────────────────

class TestUpdateProfile:
    def test_update_existing(self):
        pb.create_profile({"id": "up-p1", "name": "Old"})
        updated = pb.update_profile("up-p1", {"name": "New"})
        assert updated is not None
        assert updated.name == "New"

    def test_update_missing_returns_none(self):
        assert pb.update_profile("nonexistent", {"name": "New"}) is None

    def test_update_does_not_change_id(self):
        pb.create_profile({"id": "up-id-p1", "name": "Test"})
        updated = pb.update_profile("up-id-p1", {"id": "hacked-id"})
        assert updated.id == "up-id-p1"


# ─── delete_profile ─────────────────────────────────────────────────────────

class TestDeleteProfile:
    def test_delete_existing(self):
        pb.create_profile({"id": "del-p1", "name": "ToDelete"})
        assert pb.delete_profile("del-p1") is True
        assert pb.get_profile("del-p1") is None

    def test_delete_missing_returns_false(self):
        assert pb.delete_profile("nonexistent") is False


# ─── warmup_profile ─────────────────────────────────────────────────────────

class TestWarmupProfile:
    def test_warmup_existing(self):
        pb.create_profile({"id": "warm-p1", "name": "WarmTest"})
        result = pb.warmup_profile("warm-p1")
        assert result is not None
        assert result.id == "warm-p1"

    def test_warmup_missing_returns_none(self):
        assert pb.warmup_profile("nonexistent") is None


# ─── export_profile ─────────────────────────────────────────────────────────

class TestExportProfile:
    def test_export_existing(self):
        pb.create_profile({"id": "exp-p1", "name": "ExportTest", "tags": ["t1"]})
        data = pb.export_profile("exp-p1")
        assert data is not None
        assert data["id"] == "exp-p1"
        assert data["name"] == "ExportTest"
        assert data["tags"] == ["t1"]
        # storage_dir 不应出现在导出中
        assert "storage_dir" not in data or data.get("storage_dir") is None

    def test_export_missing_returns_none(self):
        assert pb.export_profile("nonexistent") is None


# ─── import_profile ─────────────────────────────────────────────────────────

class TestImportProfile:
    def test_import_new(self):
        data = {"id": "imp-p1", "name": "Imported", "tags": ["imported"]}
        p = pb.import_profile(data)
        assert p.id == "imp-p1"
        assert p.name == "Imported"
        assert p.tags == ["imported"]

    def test_import_without_id_generates(self):
        p = pb.import_profile({"name": "NoId"})
        assert p.id != ""

    def test_import_duplicate_overwrites(self):
        pb.create_profile({"id": "imp-dup", "name": "Original"})
        data = {"id": "imp-dup", "name": "Overwritten"}
        p = pb.import_profile(data)
        assert p.name == "Overwritten"


# ─── Pool 状态管理（T-090 / T-091）────────────────────────────────────────

class TestPoolManagement:
    def test_set_pool_strategy(self):
        pb.set_pool_strategy("round_robin")
        status = pb.get_pool_status()
        assert status["strategy"] == "round_robin"

    def test_set_pool_max_concurrent(self):
        pb.set_pool_max_concurrent(5)
        status = pb.get_pool_status()
        assert status["max_concurrent"] == 5

    def test_set_pool_max_concurrent_invalid_raises(self):
        with pytest.raises(ValueError):
            pb.set_pool_max_concurrent(0)

    def test_uncooldown_profile(self):
        import time
        p = pb.create_profile({"id": "cool-p1", "name": "CooldownTest"})
        # 手动设置 cooldown 状态
        p.status = ProfileStatus.COOLDOWN
        p.cooldown_until = time.time() + 300
        pb._get_store().save(p)

        assert pb.uncooldown_profile("cool-p1") is True
        updated = pb.get_profile("cool-p1")
        assert updated.status == ProfileStatus.READY
        assert updated.cooldown_until is None

    def test_uncooldown_missing_returns_false(self):
        assert pb.uncooldown_profile("nonexistent-cool") is False

    def test_uncooldown_non_cooldown_returns_false(self):
        p = pb.create_profile({"id": "ready-p1", "name": "ReadyTest"})
        assert p.status == ProfileStatus.READY
        assert pb.uncooldown_profile("ready-p1") is False
