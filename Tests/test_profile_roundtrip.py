"""
Tests/test_profile_roundtrip.py — FINGERPRINT-001 验收测试
Profile.to_dict() / from_dict() YAML roundtrip 单元测试
"""
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.profile import Profile, FingerprintConfig, NetworkConfig, ProfileStatus


class TestProfileRoundtrip:
    """FINGERPRINT-001: Profile YAML roundtrip"""

    def test_profile_basic_roundtrip(self):
        """基本 Profile 序列化/反序列化"""
        p = Profile(id="test-001", name="Test Profile", tags=["dev", "test"])
        d = p.to_dict()
        p2 = Profile.from_dict(d)
        assert p2.id == p.id
        assert p2.name == p.name
        assert p2.tags == p.tags
        assert p2.fingerprint.user_agent == p.fingerprint.user_agent

    def test_profile_with_seeds_roundtrip(self):
        """带明确 seed 的 Profile roundtrip"""
        p = Profile(id="seed-test")
        p.fingerprint.canvas_seed = 12345
        p.fingerprint.audio_seed = 67890
        p.fingerprint.platform = "Win64"
        p.fingerprint.locale = "en-US"
        p.fingerprint.timezone = "America/New_York"
        p.fingerprint.screen_resolution = (2560, 1440)

        d = p.to_dict()
        p2 = Profile.from_dict(d)
        assert p2.fingerprint.canvas_seed == 12345
        assert p2.fingerprint.audio_seed == 67890
        assert p2.fingerprint.platform == "Win64"
        assert p2.fingerprint.locale == "en-US"
        assert p2.fingerprint.timezone == "America/New_York"
        assert p2.fingerprint.screen_resolution == (2560, 1440)

    def test_profile_yaml_file_roundtrip(self):
        """YAML 文件写入/读取 roundtrip（模拟 store.py 持久化）"""
        with tempfile.TemporaryDirectory() as td:
            p = Profile(id="yaml-test", name="YAML Test Profile")
            p.fingerprint.canvas_seed = 999
            p.fingerprint.audio_seed = 888
            p.fingerprint.hardware_concurrency = 16
            p.fingerprint.device_memory = 32
            p.network.proxy_url = "http://user:pass@proxy.example.com:8080"
            p.network.geoip_country = "US"
            p.tags = ["production", "us-east"]

            config_path = Path(td) / "config.yaml"

            # 写入 YAML（store.py 的 write 格式）
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(p.to_dict(), f, allow_unicode=True, default_flow_style=False)

            # 读取 YAML（store.py 的 read 格式）
            with open(config_path, "r", encoding="utf-8") as f:
                loaded_data = yaml.safe_load(f)

            p2 = Profile.from_dict(loaded_data)

            assert p2.id == "yaml-test"
            assert p2.name == "YAML Test Profile"
            assert p2.fingerprint.canvas_seed == 999
            assert p2.fingerprint.audio_seed == 888
            assert p2.fingerprint.hardware_concurrency == 16
            assert p2.fingerprint.device_memory == 32
            assert p2.network.proxy_url == "http://user:pass@proxy.example.com:8080"
            assert p2.network.geoip_country == "US"
            assert p2.tags == ["production", "us-east"]

    def test_profile_status_roundtrip(self):
        """ProfileStatus 枚举 roundtrip"""
        for status in ProfileStatus:
            p = Profile(id="status-test", name="Status Test")
            p.status = status
            d = p.to_dict()
            p2 = Profile.from_dict(d)
            assert p2.status == status

    def test_profile_network_roundtrip(self):
        """NetworkConfig roundtrip"""
        net = NetworkConfig(
            proxy_url="socks5://user:pass@host:1080",
            proxy_type="socks5",
            geoip_country="JP",
            dns_over_https=False,
        )
        d = net.to_dict()
        net2 = NetworkConfig.from_dict(d)
        assert net2.proxy_url == net.proxy_url
        assert net2.proxy_type == net.proxy_type
        assert net2.geoip_country == net.geoip_country
        assert net2.dns_over_https == net.dns_over_https

    def test_fingerprint_config_roundtrip(self):
        """FingerprintConfig 完整字段 roundtrip"""
        fp = FingerprintConfig(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0",
            platform="Win64",
            vendor="Google Inc.",
            locale="zh-CN",
            timezone="Asia/Shanghai",
            screen_resolution=(1920, 1080),
            color_depth=24,
            hardware_concurrency=16,
            device_memory=16,
            canvas_seed=42,
            webgl_vendor="NVIDIA",
            webgl_renderer="NVIDIA GeForce RTX 3080",
            audio_seed=77,
            webdriver=True,
            headless_sanitize=False,
        )
        d = fp.to_dict()
        fp2 = FingerprintConfig.from_dict(d)
        assert fp2.user_agent == fp.user_agent
        assert fp2.platform == fp.platform
        assert fp2.canvas_seed == fp.canvas_seed
        assert fp2.audio_seed == fp.audio_seed
        assert fp2.webdriver == fp.webdriver
        assert fp2.screen_resolution == (1920, 1080)

    def test_profile_from_dict_idempotent(self):
        """连续两次 from_dict 结果一致"""
        p = Profile(id="idem-test", name="Idempotent Test")
        p.fingerprint.canvas_seed = 555
        d = p.to_dict()
        p2 = Profile.from_dict(d)
        d2 = p2.to_dict()
        p3 = Profile.from_dict(d2)
        assert p3.id == p.id
        assert p3.fingerprint.canvas_seed == p.fingerprint.canvas_seed
