"""
Tests/test_antidetect_profile_sync.py — T-011 验收测试

Profile.apply_to_antidetect() 7 项字段同步验证
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.profile import Profile, FingerprintConfig
from Core.AntiDetect import AntiDetectConfig


class TestApplyToAntidetect7Fields:
    """T-011: 7 项字段全部同步到 AntiDetectConfig"""

    def test_fingerprint_seed_synced(self):
        """1. fingerprint_seed → cfg.fingerprint_seed"""
        p = Profile(id="sync-seed")
        p.fingerprint.canvas_seed = 12345
        cfg = AntiDetectConfig()
        p.apply_to_antidetect(cfg)
        assert cfg.fingerprint_seed == 12345

    def test_locale_synced(self):
        """2. locale → cfg.navigator_locale"""
        p = Profile(id="sync-locale")
        p.fingerprint.locale = "zh-CN"
        cfg = AntiDetectConfig()
        p.apply_to_antidetect(cfg)
        assert cfg.navigator_locale == "zh-CN"

    def test_timezone_synced(self):
        """3. timezone → cfg.timezone"""
        p = Profile(id="sync-tz")
        p.fingerprint.timezone = "Asia/Shanghai"
        cfg = AntiDetectConfig()
        p.apply_to_antidetect(cfg)
        assert cfg.timezone == "Asia/Shanghai"

    def test_platform_synced(self):
        """4. platform → cfg.navigator_platform"""
        p = Profile(id="sync-platform")
        p.fingerprint.platform = "Win64"
        cfg = AntiDetectConfig()
        p.apply_to_antidetect(cfg)
        assert cfg.navigator_platform == "Win64"

    def test_vendor_synced(self):
        """5. vendor → cfg.webgl_vendor"""
        p = Profile(id="sync-vendor")
        p.fingerprint.vendor = "Google Inc."
        cfg = AntiDetectConfig()
        p.apply_to_antidetect(cfg)
        assert cfg.webgl_vendor == "Google Inc."

    def test_screen_resolution_synced(self):
        """6. screen_resolution → cfg.screen_width / screen_height"""
        p = Profile(id="sync-screen")
        p.fingerprint.screen_resolution = (2560, 1440)
        cfg = AntiDetectConfig()
        p.apply_to_antidetect(cfg)
        assert cfg.screen_width == 2560
        assert cfg.screen_height == 1440

    def test_hardware_concurrency_synced(self):
        """7a. hardware_concurrency → cfg.hardware_concurrency"""
        p = Profile(id="sync-hw")
        p.fingerprint.hardware_concurrency = 16
        cfg = AntiDetectConfig()
        p.apply_to_antidetect(cfg)
        assert cfg.hardware_concurrency == 16

    def test_device_memory_synced(self):
        """7b. device_memory → cfg.device_memory"""
        p = Profile(id="sync-mem")
        p.fingerprint.device_memory = 16
        cfg = AntiDetectConfig()
        p.apply_to_antidetect(cfg)
        assert cfg.device_memory == 16

    def test_all_7_fields_together(self):
        """7 项一起验证：智谱真实场景"""
        p = Profile(id="zhipu-real")
        p.fingerprint.locale = "zh-CN"
        p.fingerprint.timezone = "Asia/Shanghai"
        p.fingerprint.platform = "Win64"
        p.fingerprint.vendor = "Google Inc."
        p.fingerprint.screen_resolution = (1920, 1080)
        p.fingerprint.hardware_concurrency = 8
        p.fingerprint.device_memory = 8
        p.fingerprint.canvas_seed = 99999

        cfg = AntiDetectConfig()
        p.apply_to_antidetect(cfg)

        assert cfg.fingerprint_seed == 99999
        assert cfg.navigator_locale == "zh-CN"
        assert cfg.timezone == "Asia/Shanghai"
        assert cfg.navigator_platform == "Win64"
        assert cfg.webgl_vendor == "Google Inc."
        assert cfg.screen_width == 1920
        assert cfg.screen_height == 1080
        assert cfg.hardware_concurrency == 8
        assert cfg.device_memory == 8

    def test_backward_compatibility_no_override(self):
        """apply_to_antidetect 不存在字段不报错"""
        p = Profile(id="compat-test")
        p.fingerprint.locale = "en-US"
        cfg = AntiDetectConfig()
        # 不应抛异常
        p.apply_to_antidetect(cfg)
        assert cfg.navigator_locale == "en-US"


class TestAntidetectScriptLocaleConsistency:
    """T-011: JS 注入脚本里 locale/timezone/platform 用 config 同步值"""

    def test_locale_script_uses_config_values(self):
        """_locale_consistency_script 生成正确的 JS，使用 config 值"""
        cfg = AntiDetectConfig()
        cfg.navigator_locale = "zh-CN"
        cfg.timezone = "Asia/Shanghai"
        cfg.navigator_platform = "Win64"

        from Core.AntiDetect import AntiDetectInjector
        injector = AntiDetectInjector(cfg)
        script = injector._locale_consistency_script()

        # JS 字符串里必须包含 config 同步值
        assert "zh-CN" in script, f"locale 'zh-CN' not in script"
        assert "Asia/Shanghai" in script, f"timezone not in script"
        assert "Win64" in script, f"platform 'Win64' not in script"

    def test_hardware_script_uses_config_values(self):
        """_consistent_hardware_script 使用 config.screen_width/height"""
        cfg = AntiDetectConfig()
        cfg.screen_width = 2560
        cfg.screen_height = 1440
        cfg.hardware_concurrency = 16
        cfg.device_memory = 16

        from Core.AntiDetect import AntiDetectInjector
        injector = AntiDetectInjector(cfg)
        script = injector._consistent_hardware_script()

        assert "2560" in script, f"screen_width 2560 not in script"
        assert "1440" in script, f"screen_height 1440 not in script"
        assert "16" in script, f"hardware_concurrency 16 not in script"

    def test_webgl_vendor_uses_config(self):
        """_fingerprint_v2_script 使用 config.webgl_vendor"""
        cfg = AntiDetectConfig()
        cfg.webgl_vendor = "Apple Inc."
        cfg.webgl_renderer = "Apple M2"

        from Core.AntiDetect import AntiDetectInjector
        injector = AntiDetectInjector(cfg)
        script = injector._fingerprint_v2_script()

        assert "Apple Inc." in script, f"webgl_vendor not in script"
        assert "Apple M2" in script, f"webgl_renderer not in script"


class TestCanvasHashStability:
    """T-047 验收补充：canvas_hash 跨重启 byte-identical

    验证 fingerprint_seed → canvas_hash 确定性：
    同样 canvas_seed 两次生成，hash 完全相同（byte-identical）。

    当前实现状态：Core/AntiDetect.py 未暴露 canvas_hash 公开 API。
    本测试在 AntiDetect 暴露 canvas_hash 后启用（移除 skip）。
    """

    @pytest.mark.skip(
        reason="AntiDetect.py 未暴露 canvas_hash 公开 API；"
               "等小千在 Core/AntiDetect.py 添加 canvas_hash() 后启用本测试。"
               "追踪：XIAOCE-WAUTO-T047 canvas_hash 等待实现"
    )
    def test_canvas_hash_deterministic_same_seed(self):
        """相同 canvas_seed → 相同 canvas_hash（byte-identical）"""
        from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector
        cfg_a = AntiDetectConfig()
        cfg_a.fingerprint_seed = 42
        cfg_a.canvas_seed = 42
        injector_a = AntiDetectInjector(cfg_a)
        hash_a = injector_a.canvas_hash()

        cfg_b = AntiDetectConfig()
        cfg_b.fingerprint_seed = 42
        cfg_b.canvas_seed = 42
        injector_b = AntiDetectInjector(cfg_b)
        hash_b = injector_b.canvas_hash()

        assert hash_a == hash_b, f"canvas_hash 不稳定: {hash_a!r} vs {hash_b!r}"
        assert isinstance(hash_a, bytes), f"canvas_hash 应为 bytes, 实际 {type(hash_a)}"
        assert len(hash_a) >= 16, f"canvas_hash 太短: {len(hash_a)} 字节"

    @pytest.mark.skip(
        reason="AntiDetect.py 未暴露 canvas_hash 公开 API；"
               "等小千实现 canvas_hash() 后启用。"
    )
    def test_canvas_hash_differs_across_profiles(self):
        """不同 Profile（不同 canvas_seed）→ 不同 canvas_hash"""
        from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector
        cfg_a = AntiDetectConfig()
        cfg_a.canvas_seed = 100
        injector_a = AntiDetectInjector(cfg_a)
        hash_a = injector_a.canvas_hash()

        cfg_b = AntiDetectConfig()
        cfg_b.canvas_seed = 200
        injector_b = AntiDetectInjector(cfg_b)
        hash_b = injector_b.canvas_hash()

        assert hash_a != hash_b, "不同 canvas_seed 应当产生不同 hash"

    @pytest.mark.skip(
        reason="AntiDetect.py 未暴露 canvas_hash 公开 API；"
               "等小千实现 canvas_hash() 后启用。"
    )
    def test_canvas_hash_byte_identical_across_restarts(self):
        """跨进程重启：相同 seed → byte-identical hash

        模拟两个独立 AntiDetectInjector 实例（同 seed）：
        - 实例 1 启动 → 生成 hash_a
        - 实例 1 销毁
        - 实例 2 启动（同 seed）→ 生成 hash_b
        - 验证 hash_a == hash_b（无随机性，无时间戳依赖）
        """
        from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector

        seed = 7777
        hash_a = None
        # 第一轮
        cfg = AntiDetectConfig()
        cfg.canvas_seed = seed
        cfg.fingerprint_seed = seed
        injector = AntiDetectInjector(cfg)
        hash_a = injector.canvas_hash()

        # 第二轮（新实例，模拟重启）
        cfg2 = AntiDetectConfig()
        cfg2.canvas_seed = seed
        cfg2.fingerprint_seed = seed
        injector2 = AntiDetectInjector(cfg2)
        hash_b = injector2.canvas_hash()

        assert hash_a == hash_b, "canvas_hash 跨重启不一致（违反确定性）"
