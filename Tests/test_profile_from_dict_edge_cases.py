"""
Tests/test_profile_from_dict_edge_cases.py — T-068 Profile from_dict / to_dict 边界 case 全覆盖

验收标准：空字符串 / None / 超长值 / 非法枚举 / 缺失必填字段 等边界 case 全覆盖，测试全过

覆盖范围：
- Profile.from_dict() 非法 status 值
- 空字符串 id / name
- None 值（cooldown_until, last_used, storage_dir）
- 缺失必填字段
- to_dict → from_dict 幂等性
- 额外未知字段（应被忽略）
- 超长字符串
- FingerprintConfig 边界 case
- NetworkConfig 边界 case
"""

from __future__ import annotations

from pathlib import Path
import pytest

from Core.Profile import Profile, FingerprintConfig, NetworkConfig, ProfileStatus


# ─── Profile.from_dict 边界 case ─────────────────────────────────────────────

class TestProfileFromDictEdgeCases:
    def test_empty_id_defaults_to_uuid(self):
        """id 为空字符串时，__post_init__ 自动生成 8 位 UUID"""
        p = Profile.from_dict({"id": "", "name": "test"})
        assert p.id != ""
        assert len(p.id) == 8
        assert p.name == "test"

    def test_empty_name_defaults_to_id(self):
        """name 为空字符串时，__post_init__ 自动设为 id 值"""
        p = Profile.from_dict({"id": "my-id", "name": ""})
        assert p.name == "my-id"
        assert p.id == "my-id"

    def test_none_status_defaults_to_ready(self):
        """status=None 时默认 READY"""
        p = Profile.from_dict({"id": "p1", "status": None})
        assert p.status == ProfileStatus.READY

    def test_illegal_status_value_raises(self):
        """非法 status 字符串应抛出 ValueError"""
        with pytest.raises(ValueError):
            Profile.from_dict({"id": "p1", "status": "NOT_A_STATUS"})

    def test_lowercase_status_accepted(self):
        """status 大小写不敏感，小写 'ready' 等于 READY"""
        p = Profile.from_dict({"id": "p1", "status": "ready"})
        assert p.status == ProfileStatus.READY

    def test_missing_id_generates_uuid(self):
        """完全缺失 id 字段时自动生成"""
        p = Profile.from_dict({"name": "no-id-profile"})
        assert p.id != ""
        assert len(p.id) == 8

    def test_none_cooldown_until_allowed(self):
        """cooldown_until=None 是合法值"""
        p = Profile.from_dict({
            "id": "p1",
            "cooldown_until": None,
            "last_used": None,
        })
        assert p.cooldown_until is None
        assert p.last_used is None

    def test_negative_cooldown_until_allowed(self):
        """cooldown_until 为负数（过去时间戳）是合法值，表示已过期"""
        p = Profile.from_dict({
            "id": "p1",
            "cooldown_until": -1.0,
        })
        assert p.cooldown_until == -1.0

    def test_extra_unknown_fields_ignored(self):
        """from_dict 忽略未知字段，不抛异常"""
        data = {
            "id": "p1",
            "name": "test",
            "unknown_field": "should_be_ignored",
            "another_extra": 12345,
        }
        p = Profile.from_dict(data)
        assert p.id == "p1"
        assert not hasattr(p, "unknown_field")

    def test_empty_tags_list(self):
        """tags=[] 是合法值"""
        p = Profile.from_dict({"id": "p1", "tags": []})
        assert p.tags == []

    def test_tags_with_duplicates(self):
        """tags 可以包含重复值"""
        p = Profile.from_dict({"id": "p1", "tags": ["a", "a", "b"]})
        assert p.tags == ["a", "a", "b"]

    def test_empty_browser_args_list(self):
        """browser_args=[] 是合法值"""
        p = Profile.from_dict({"id": "p1", "browser_args": []})
        assert p.browser_args == []

    def test_empty_extensions_list(self):
        """extensions=[] 是合法值"""
        p = Profile.from_dict({"id": "p1", "extensions": []})
        assert p.extensions == []

    def test_empty_custom_scripts_list(self):
        """custom_scripts=[] 是合法值"""
        p = Profile.from_dict({"id": "p1", "custom_scripts": []})
        assert p.custom_scripts == []

    def test_very_long_string_accepted(self):
        """超长字符串（>10KB）应该被接受（不截断）"""
        long_name = "x" * 20000
        p = Profile.from_dict({"id": "p1", "name": long_name})
        assert p.name == long_name
        assert len(p.name) == 20000

    def test_unicode_name_accepted(self):
        """Unicode 名字应该被接受"""
        p = Profile.from_dict({"id": "p1", "name": "你好世界 🌍"})
        assert p.name == "你好世界 🌍"

    def test_storage_dir_none_defaults_to_none(self):
        """storage_dir=None 时保持 None"""
        p = Profile.from_dict({"id": "p1", "storage_dir": None})
        assert p.storage_dir is None

    def test_storage_dir_string_path_converted(self):
        """storage_dir 是字符串时转为 Path"""
        p = Profile.from_dict({"id": "p1", "storage_dir": "/tmp/test"})
        assert p.storage_dir == Path("/tmp/test")

    def test_all_status_enum_values_work(self):
        """所有 ProfileStatus 枚举值都能被 from_dict 接受"""
        for status in ProfileStatus:
            p = Profile.from_dict({"id": "p1", "status": status.value})
            assert p.status == status


# ─── FingerprintConfig 边界 case ──────────────────────────────────────────────

class TestFingerprintConfigEdgeCases:
    def test_empty_user_agent(self):
        """空字符串 user_agent 是合法值"""
        fp = FingerprintConfig.from_dict({"user_agent": ""})
        assert fp.user_agent == ""

    def test_very_long_user_agent(self):
        """超长 user_agent 字符串应被接受"""
        long_ua = "Mozilla/5.0 " + "x" * 5000
        fp = FingerprintConfig.from_dict({"user_agent": long_ua})
        assert fp.user_agent == long_ua

    def test_screen_resolution_list_converted_to_tuple(self):
        """screen_resolution 传入 list 时自动转 tuple"""
        fp = FingerprintConfig.from_dict({
            "screen_resolution": [1920, 1080],
        })
        assert fp.screen_resolution == (1920, 1080)

    def test_screen_resolution_tuple_unchanged(self):
        """screen_resolution 传入 tuple 时保持不变"""
        fp = FingerprintConfig.from_dict({
            "screen_resolution": (2560, 1440),
        })
        assert fp.screen_resolution == (2560, 1440)

    def test_screen_resolution_string_accepted(self):
        """screen_resolution 传入字符串时直接赋给 dataclass 字段（由调用方保证类型正确）"""
        fp = FingerprintConfig.from_dict({
            "screen_resolution": "1920x1080",  # 字符串，dataclass 接受任意类型
        })
        # from_dict 不过滤合法字段名，只过滤未知字段名
        assert fp.screen_resolution == "1920x1080"

    def test_extra_fingerprint_fields_ignored(self):
        """FingerprintConfig 忽略未知字段"""
        fp = FingerprintConfig.from_dict({
            "user_agent": "test",
            "unknown_fp_field": "ignored",
        })
        assert fp.user_agent == "test"
        assert not hasattr(fp, "unknown_fp_field")


# ─── NetworkConfig 边界 case ──────────────────────────────────────────────────

class TestNetworkConfigEdgeCases:
    def test_none_proxy_url(self):
        """proxy_url=None 是合法值"""
        nc = NetworkConfig.from_dict({"proxy_url": None})
        assert nc.proxy_url is None

    def test_empty_proxy_url(self):
        """proxy_url='' 是合法值"""
        nc = NetworkConfig.from_dict({"proxy_url": ""})
        assert nc.proxy_url == ""

    def test_proxy_url_with_auth(self):
        """带认证的 proxy_url 正常解析"""
        nc = NetworkConfig.from_dict({
            "proxy_url": "http://user:pass@proxy.com:8080"
        })
        assert nc.proxy_url == "http://user:pass@proxy.com:8080"

    def test_get_playwright_proxy_none_url(self):
        """proxy_url=None 时 get_playwright_proxy 返回 None"""
        nc = NetworkConfig()
        assert nc.get_playwright_proxy() is None

    def test_extra_network_fields_ignored(self):
        """NetworkConfig 忽略未知字段"""
        nc = NetworkConfig.from_dict({
            "proxy_url": None,
            "unknown_net_field": "ignored",
        })
        assert not hasattr(nc, "unknown_net_field")


# ─── to_dict → from_dict 幂等性 ───────────────────────────────────────────────

class TestProfileRoundtripIdempotent:
    def test_to_dict_from_dict_idempotent_minimal(self):
        """最小 Profile 往返后内容一致"""
        original = Profile(id="p1", name="test")
        data = original.to_dict()
        restored = Profile.from_dict(data)
        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.status == original.status

    def test_to_dict_from_dict_idempotent_full(self):
        """完整 Profile 往返后内容一致"""
        original = Profile(
            id="full-p1",
            name="Full Profile",
            tags=["tag1", "tag2"],
            status=ProfileStatus.COOLDOWN,
            cooldown_until=1234567890.5,
            last_used=1234567800.0,
            storage_dir=Path("/tmp/test"),
            browser_args=["--no-sandbox"],
            extensions=["ext1"],
            custom_scripts=["script1"],
        )
        data = original.to_dict()
        restored = Profile.from_dict(data)
        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.tags == original.tags
        assert restored.status == original.status
        assert restored.cooldown_until == original.cooldown_until
        assert restored.last_used == original.last_used
        assert restored.storage_dir == original.storage_dir
        assert restored.browser_args == original.browser_args
        assert restored.extensions == original.extensions
        assert restored.custom_scripts == original.custom_scripts

    def test_to_dict_from_dict_preserves_fingerprint(self):
        """往返后 fingerprint 内容一致"""
        original = Profile(
            id="fp-p1",
            fingerprint=FingerprintConfig(
                user_agent="Custom UA",
                platform="Win32",
                vendor="Test Vendor",
            ),
        )
        data = original.to_dict()
        restored = Profile.from_dict(data)
        assert restored.fingerprint.user_agent == original.fingerprint.user_agent
        assert restored.fingerprint.platform == original.fingerprint.platform
        assert restored.fingerprint.vendor == original.fingerprint.vendor

    def test_to_dict_from_dict_preserves_network(self):
        """往返后 network 内容一致"""
        original = Profile(
            id="net-p1",
            network=NetworkConfig(
                proxy_url="http://user:pass@proxy.com:8080",
                proxy_username="user",
                proxy_password="pass",
            ),
        )
        data = original.to_dict()
        restored = Profile.from_dict(data)
        assert restored.network.proxy_url == original.network.proxy_url

    def test_status_enum_roundtrip(self):
        """所有 status 枚举值往返后一致"""
        for status in ProfileStatus:
            original = Profile.from_dict({"id": "p1", "status": status.value})
            data = original.to_dict()
            restored = Profile.from_dict(data)
            assert restored.status == status
