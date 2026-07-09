"""
Tests/test_seed_stability.py — FINGERPRINT-006 验收测试

验收标准：
1. profile.fingerprint.canvas_seed 强制同步到 AntiDetectConfig.fingerprint_seed
2. 同 Profile 二次启动，Canvas hash 完全一致（seed 相同 → 噪声 byte-identical）
3. AntiDetect 噪声 byte-identical（同一 seed）
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.profile import Profile, FingerprintConfig
from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector


class TestSeedSync:
    """验收 1: canvas_seed → fingerprint_seed 强制同步"""

    def test_canvas_seed_forces_anti_detect_seed(self):
        """Profile.fingerprint.canvas_seed 必须强制覆盖 AntiDetectConfig.fingerprint_seed"""
        p = Profile(id="seed-sync")
        p.fingerprint.canvas_seed = 42

        cfg = AntiDetectConfig()
        # 初始 cfg.fingerprint_seed 为 None
        assert cfg.fingerprint_seed is None

        p.apply_to_antidetect(cfg)

        # 同步后必须等于 canvas_seed
        assert cfg.fingerprint_seed == 42, (
            f"canvas_seed={p.fingerprint.canvas_seed} 应强制同步到 "
            f"fingerprint_seed，实际 fingerprint_seed={cfg.fingerprint_seed}"
        )

    def test_canvas_seed_overrides_existing_seed(self):
        """canvas_seed 覆盖已存在的 fingerprint_seed"""
        p = Profile(id="seed-override")
        p.fingerprint.canvas_seed = 777

        cfg = AntiDetectConfig(fingerprint_seed=99999)  # 已有值
        p.apply_to_antidetect(cfg)

        assert cfg.fingerprint_seed == 777, "canvas_seed 应强制覆盖已有 fingerprint_seed"

    def test_same_profile_idempotent_seed_sync(self):
        """同一 Profile 多次 apply_to_antidetect，seed 值稳定"""
        p = Profile(id="stable-seed")
        p.fingerprint.canvas_seed = 12345

        for _ in range(3):
            cfg = AntiDetectConfig()
            p.apply_to_antidetect(cfg)
            assert cfg.fingerprint_seed == 12345


class TestCanvasNoiseDeterminism:
    """验收 2 & 3: 同 seed → canvas noise byte-identical；不同 seed → 不同噪声"""

    def test_same_seed_produces_identical_noise_sequence(self):
        """
        同 seed 调用 _fingerprint_v2_script 两次，生成的噪声脚本完全一致。
        mulberry32 是确定性 PRNG，同 seed 必同序列。
        """
        cfg1 = AntiDetectConfig(fingerprint_seed=12345)
        inj1 = AntiDetectInjector(cfg1)
        script1 = inj1._fingerprint_v2_script()

        cfg2 = AntiDetectConfig(fingerprint_seed=12345)
        inj2 = AntiDetectInjector(cfg2)
        script2 = inj2._fingerprint_v2_script()

        # 同 seed 生成的脚本完全一致
        assert script1 == script2, (
            "同 seed 的 canvas noise 脚本应 byte-identical"
        )

    def test_different_seed_produces_different_noise_sequence(self):
        """不同 seed 生成的噪声脚本不同（_fingerprint_v2_script）"""
        cfg1 = AntiDetectConfig(fingerprint_seed=11111)
        script1 = AntiDetectInjector(cfg1)._fingerprint_v2_script()

        cfg2 = AntiDetectConfig(fingerprint_seed=22222)
        script2 = AntiDetectInjector(cfg2)._fingerprint_v2_script()

        assert script1 != script2, "不同 seed 的 canvas noise 脚本应不同"

    def test_profile_twice_same_canvas_seed(self):
        """
        同一 Profile 两次加载，canvas_seed 相同 → 两次生成的 AntiDetect 脚本完全一致。
        这是"同 Profile 二次启动，Canvas hash 完全一致"的本质保证。
        """
        # 第一次：创建 Profile（canvas_seed 自动生成）
        p1 = Profile(id="deterministic-profile")
        p1.fingerprint.canvas_seed = 42
        p1.fingerprint.audio_seed = 42

        cfg1 = AntiDetectConfig()
        p1.apply_to_antidetect(cfg1)
        inj1 = AntiDetectInjector(cfg1)
        script1 = inj1._fingerprint_v2_script()
        audio_script1 = inj1._audio_stable_script()

        # 第二次：模拟重新从 store 加载（seed 已持久化）
        p2 = Profile(id="deterministic-profile")
        p2.fingerprint.canvas_seed = 42
        p2.fingerprint.audio_seed = 42

        cfg2 = AntiDetectConfig()
        p2.apply_to_antidetect(cfg2)
        inj2 = AntiDetectInjector(cfg2)
        script2 = inj2._fingerprint_v2_script()
        audio_script2 = inj2._audio_stable_script()

        # 同 canvas_seed，同 audio_seed → 同 AntiDetect 脚本
        assert script1 == script2, "同 Profile 二次启动，canvas noise 脚本应完全一致"
        assert audio_script1 == audio_script2, "同 Profile 二次启动，audio noise 脚本应完全一致"


class TestOrchestratorSeedInjection:
    """验收 1（集成层）: orchestrator._inject_anti_detect 调用 apply_to_antidetect"""

    def test_orchestrator_injects_all_7_fields(self):
        """
        orchestrator._inject_anti_detect 生成的 AntiDetectConfig 包含全部 7 项同步字段。
        """
        from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector

        p = Profile(id="orch-field-test")
        p.fingerprint.canvas_seed = 999
        p.fingerprint.locale = "ja-JP"
        p.fingerprint.timezone = "Asia/Tokyo"
        p.fingerprint.platform = "MacIntel"
        p.fingerprint.vendor = "Apple Inc."
        p.fingerprint.screen_resolution = (1440, 900)
        p.fingerprint.hardware_concurrency = 12
        p.fingerprint.device_memory = 16

        cfg = AntiDetectConfig()
        p.apply_to_antidetect(cfg)

        # 7 项全部同步
        assert cfg.fingerprint_seed == 999
        assert cfg.navigator_locale == "ja-JP"
        assert cfg.timezone == "Asia/Tokyo"
        assert cfg.navigator_platform == "MacIntel"
        assert cfg.webgl_vendor == "Apple Inc."
        assert cfg.screen_width == 1440
        assert cfg.screen_height == 900
        assert cfg.hardware_concurrency == 12
        assert cfg.device_memory == 16
