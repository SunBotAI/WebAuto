"""Tests/test_browser_profile.py - BrowserProfile 单元测试。

覆盖:
    - 默认 BrowserProfile 创建/序列化/反序列化
    - 字段越界值拒绝
    - HardwareConsistent 的硬约束
    - ProfileStore 读/写/列/删
    - get_or_create 幂等
    - apply_to_anti_detect_config 写入 fingerprint_seed
    - apply_to_playwright_kwargs 返回正确结构
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.BrowserProfile import (
    BrowserProfile,
    HardwareConsistent,
    ViewportConfig,
    ProfileStore,
)


class TestBrowserProfileConstruction:
    def test_default_creation(self):
        p = BrowserProfile(profile_id="default-test")
        assert p.profile_id == "default-test"
        assert p.fingerprint_seed >= 0
        assert p.hardware.cores in (4, 8, 12, 16)
        assert p.locale == "zh-CN"
        assert p.timezone_id == "Asia/Shanghai"

    def test_invalid_seed_raises(self):
        with pytest.raises(ValueError):
            BrowserProfile(profile_id="x", fingerprint_seed=-1)
        with pytest.raises(ValueError):
            BrowserProfile(profile_id="x", fingerprint_seed=2**31 + 1)

    def test_invalid_color_scheme_raises(self):
        with pytest.raises(ValueError):
            BrowserProfile(profile_id="x", color_scheme="purple")

    def test_hardware_invalid_cores_raises(self):
        with pytest.raises(ValueError):
            HardwareConsistent(cores=7)
        with pytest.raises(ValueError):
            HardwareConsistent(memory_gb=32)

    def test_hardware_invalid_screen_raises(self):
        with pytest.raises(ValueError):
            HardwareConsistent(screen_w=500)  # 太小

    def test_viewport_bounds(self):
        v = ViewportConfig(width=1920, height=1080)
        assert v.width == 1920
        with pytest.raises(ValueError):
            ViewportConfig(width=999)  # < 1024
        with pytest.raises(ValueError):
            ViewportConfig(height=5000)


class TestSerialization:
    def _sample(self):
        return BrowserProfile(
            profile_id="serialize-test",
            label="test label",
            fingerprint_seed=12345,
            hardware=HardwareConsistent(cores=12, memory_gb=16),
            viewport=ViewportConfig(width=1366, height=768),
        )

    def test_to_from_dict_roundtrip(self):
        p = self._sample()
        d = p.to_dict()
        p2 = BrowserProfile.from_dict(d)
        assert p2.profile_id == p.profile_id
        assert p2.fingerprint_seed == 12345
        assert p2.hardware.cores == 12
        assert p2.viewport.width == 1366

    def test_json_roundtrip_via_string(self):
        p = self._sample()
        s = json.dumps(p.to_dict(), ensure_ascii=False)
        d = json.loads(s)
        p2 = BrowserProfile.from_dict(d)
        assert p2.fingerprint_seed == 12345


class TestProfileStore:
    def setup_method(self):
        # 用临时目录替代 ~/.cache/webauto
        self.tmpdir = tempfile.mkdtemp()
        self.store = ProfileStore(root=Path(self.tmpdir))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_or_create_new(self):
        p = self.store.get_or_create("ws-01", seed=42, label="workstation")
        assert p.fingerprint_seed == 42
        assert p.profile_id == "ws-01"
        assert self.store.exists("ws-01")

    def test_get_or_create_idempotent(self):
        p1 = self.store.get_or_create("ws-02", seed=100)
        p2 = self.store.get_or_create("ws-02")  # 不传 seed
        assert p1.fingerprint_seed == p2.fingerprint_seed == 100

    def test_save_load_roundtrip(self):
        p = self.store.get_or_create("ws-03", seed=999)
        p.label = "modified"
        self.store.save(p)
        loaded = self.store.load("ws-03")
        assert loaded.label == "modified"
        assert loaded.fingerprint_seed == 999

    def test_atomic_write_no_partial(self):
        p = self.store.get_or_create("ws-04", seed=1)
        p.fingerprint_seed = 2
        self.store.save(p)
        # 任何时刻 load 都返回最新或 None,不会半写文件
        loaded = self.store.load("ws-04")
        assert loaded.fingerprint_seed == 2

    def test_list_ids(self):
        self.store.get_or_create("aaa", seed=1)
        self.store.get_or_create("bbb", seed=2)
        self.store.get_or_create("ccc", seed=3)
        ids = self.store.list_ids()
        assert set(ids) == {"aaa", "bbb", "ccc"}

    def test_delete(self):
        self.store.get_or_create("ws-delete", seed=1)
        assert self.store.exists("ws-delete")
        self.store.delete("ws-delete")
        assert not self.store.exists("ws-delete")

    def test_load_missing_returns_none(self):
        assert self.store.load("nonexistent") is None


class TestApplyToAntiDetectConfig:
    def test_apply_seed_only(self):
        from Core.AntiDetect import AntiDetectConfig
        cfg = AntiDetectConfig()
        cfg.fingerprint_seed = 999
        p = BrowserProfile(profile_id="x", fingerprint_seed=12345)
        p.apply_to_anti_detect_config(cfg)
        assert cfg.fingerprint_seed == 12345

    def test_apply_to_playwright_kwargs(self):
        p = BrowserProfile(
            profile_id="x",
            viewport=ViewportConfig(width=1366, height=768),
            locale="en-US",
            timezone_id="America/Los_Angeles",
        )
        kw = p.apply_to_playwright_kwargs()
        assert kw["viewport"] == {"width": 1366, "height": 768}
        assert kw["locale"] == "en-US"
        assert kw["timezone_id"] == "America/Los_Angeles"

    def test_apply_to_http_headers(self):
        p = BrowserProfile(
            profile_id="x",
            user_agent="Custom/1.0",
            accept_language="en;q=0.9",
        )
        h = p.apply_to_http_headers()
        assert h["User-Agent"] == "Custom/1.0"
        assert h["Accept-Language"] == "en;q=0.9"
        assert "sec-ch-ua" in h
