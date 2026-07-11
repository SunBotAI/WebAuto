"""
Tests/test_profile_backend_bulk.py — T-092 ProfileService 批量操作测试

测试:
    bulk_update_tags(ids, add_tags, remove_tags)
    bulk_set_status(ids, status)
"""

import pytest
import tempfile
import shutil
from pathlib import Path

from Core.Profile import Profile, ProfileStore, ProfileStatus
import Tools.profile_backend as pb


@pytest.fixture
def store():
    tmp = tempfile.mkdtemp()
    s = ProfileStore(base_dir=Path(tmp))
    # 创建 12 个 profile（10 个测试批量 + 2 个边界）
    for i in range(12):
        p = Profile.from_dict({
            "id": f"bulk-{i:02d}",
            "name": f"Bulk-{i:02d}",
            "status": "ready",
            "tags": [f"group-A"] if i < 6 else [f"group-B"],
            "fingerprint": {
                "platform": "windows",
                "user_agent": "Mozilla/5.0",
                "viewport": {"width": 1920, "height": 1080},
                "timezone": "Asia/Shanghai",
                "locale": "zh-CN",
                "ua_mask_type": "masked",
            },
            "network": {
                "proxy_url": "",
                "proxy_username": "",
                "proxy_password": "",
                "proxy_type": "http",
                "geoip_country": "",
                "dns_over_https": True,
                "proxy_pool": [],
            },
        })
        s.save(p)
    yield s
    shutil.rmtree(tmp)


@pytest.fixture(autouse=True)
def patch_backend_store(store, monkeypatch):
    """替换 pb 模块内部单例，指向测试 store。"""
    pb._store = store
    pb._pool = None
    yield


class TestBulkUpdateTags:
    def test_add_tags_to_10_profiles(self):
        ids = [f"bulk-{i:02d}" for i in range(10)]
        result = pb.bulk_update_tags(ids, add_tags=["tag-new"])

        assert len(result["succeeded"]) == 10, f"expected 10 succeeded, got {result}"
        assert len(result["failed"]) == 0

        # 验证全部都加上了 tag-new
        for pid in ids:
            p = pb.get_profile(pid)
            assert "tag-new" in p.tags

    def test_remove_tags_from_10_profiles(self):
        ids = [f"bulk-{i:02d}" for i in range(6)]  # 前6个有 group-A
        result = pb.bulk_update_tags(ids, remove_tags=["group-A"])

        assert len(result["succeeded"]) == 6
        assert len(result["failed"]) == 0

        for pid in ids:
            p = pb.get_profile(pid)
            assert "group-A" not in p.tags

    def test_add_and_remove_tags_simultaneously(self):
        ids = [f"bulk-{i:02d}" for i in range(6)]
        result = pb.bulk_update_tags(ids, add_tags=["tag-added"], remove_tags=["group-A"])

        assert len(result["succeeded"]) == 6
        for pid in ids:
            p = pb.get_profile(pid)
            assert "tag-added" in p.tags
            assert "group-A" not in p.tags

    def test_empty_ids(self):
        result = pb.bulk_update_tags([], add_tags=["tag"])
        assert result["succeeded"] == []
        assert result["failed"] == []

    def test_partial_failure(self):
        ids = [f"bulk-{i:02d}" for i in range(3)] + ["non-existent-id"]
        result = pb.bulk_update_tags(ids, add_tags=["tag-partial"])

        assert len(result["succeeded"]) == 3
        assert len(result["failed"]) == 1
        assert result["failed"][0][0] == "non-existent-id"


class TestBulkSetStatus:
    def test_set_status_to_10_profiles(self):
        ids = [f"bulk-{i:02d}" for i in range(10)]
        result = pb.bulk_set_status(ids, ProfileStatus.COOLDOWN)

        assert len(result["succeeded"]) == 10, f"expected 10 succeeded, got {result}"
        assert len(result["failed"]) == 0

        for pid in ids:
            p = pb.get_profile(pid)
            assert p.status == ProfileStatus.COOLDOWN

    def test_set_banned_status(self):
        ids = [f"bulk-{i:02d}" for i in range(5)]
        result = pb.bulk_set_status(ids, ProfileStatus.BANNED)

        assert len(result["succeeded"]) == 5
        for pid in ids:
            p = pb.get_profile(pid)
            assert p.status == ProfileStatus.BANNED

    def test_set_ready_status(self):
        ids = [f"bulk-{i:02d}" for i in range(4)]
        # 先全设 COOLDOWN
        pb.bulk_set_status(ids, ProfileStatus.COOLDOWN)
        # 再设回 READY
        result = pb.bulk_set_status(ids, ProfileStatus.READY)

        assert len(result["succeeded"]) == 4
        for pid in ids:
            p = pb.get_profile(pid)
            assert p.status == ProfileStatus.READY

    def test_empty_ids(self):
        result = pb.bulk_set_status([], ProfileStatus.READY)
        assert result["succeeded"] == []
        assert result["failed"] == []

    def test_partial_failure(self):
        ids = ["bulk-00", "bulk-01", "non-existent-99"]
        result = pb.bulk_set_status(ids, ProfileStatus.BANNED)

        assert len(result["succeeded"]) == 2
        assert len(result["failed"]) == 1
        assert result["failed"][0][0] == "non-existent-99"
