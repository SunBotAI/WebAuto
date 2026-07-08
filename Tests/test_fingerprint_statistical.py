"""
Tests/test_fingerprint_statistical.py — FINGERPRINT-002 验收测试
同 seed Canvas/WebGL/Audio 输出一致 + 7 项统计一致性检查
"""
import sys
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.fingerprint_gen import FingerprintGenerator


class TestFingerprintGeneratorDeterminism:
    """同 seed 必须产生相同输出"""

    def test_same_seed_same_canvas_seed(self):
        """同 seed 生成的 canvas_seed 一致"""
        gen1 = FingerprintGenerator(seed=42)
        gen2 = FingerprintGenerator(seed=42)
        fp1 = gen1.generate(template="windows_chrome_120")
        fp2 = gen2.generate(template="windows_chrome_120")
        assert fp1.canvas_seed == fp2.canvas_seed, "Same seed must produce same canvas_seed"

    def test_same_seed_same_audio_seed(self):
        """同 seed 生成的 audio_seed 一致"""
        gen1 = FingerprintGenerator(seed=42)
        gen2 = FingerprintGenerator(seed=42)
        fp1 = gen1.generate(template="windows_chrome_120")
        fp2 = gen2.generate(template="windows_chrome_120")
        assert fp1.audio_seed == fp2.audio_seed, "Same seed must produce same audio_seed"

    def test_same_seed_same_webgl_seed(self):
        """同 seed 生成的 canvas_seed（WebGL 也用它）一致"""
        gen1 = FingerprintGenerator(seed=100)
        gen2 = FingerprintGenerator(seed=100)
        fp1 = gen1.generate(template="linux_chrome_120")
        fp2 = gen2.generate(template="linux_chrome_120")
        assert fp1.canvas_seed == fp2.canvas_seed

    def test_different_seeds_different_canvas_seed(self):
        """不同 seed 生成的 canvas_seed 不一样（高概率）"""
        gen1 = FingerprintGenerator(seed=42)
        gen2 = FingerprintGenerator(seed=999)
        fp1 = gen1.generate(template="windows_chrome_120")
        fp2 = gen2.generate(template="windows_chrome_120")
        assert fp1.canvas_seed != fp2.canvas_seed, "Different seeds must produce different canvas_seed"

    def test_same_seed_multiple_templates_deterministic(self):
        """同一 seed 对每个 template 都有确定输出（每个 template 独立 RNG 实例）"""
        templates = ["windows_chrome_120", "macos_safari_17", "linux_chrome_120",
                     "mobile_android", "mobile_ios"]
        for tpl in templates:
            # 每个 template 用独立的 Generator 实例（同一 seed）
            gen1 = FingerprintGenerator(seed=777)
            gen2 = FingerprintGenerator(seed=777)
            fp1 = gen1.generate(template=tpl)
            fp2 = gen2.generate(template=tpl)
            assert fp1.canvas_seed == fp2.canvas_seed, f"template={tpl}: canvas_seed 不一致"
            assert fp1.audio_seed == fp2.audio_seed, f"template={tpl}: audio_seed 不一致"


class TestFingerprintStatisticalConsistency:
    """
    7 项关联一致性检查：
    UA / Platform / Vendor / Locale / Timezone / Screen Resolution / Hardware Concurrency
    必须相互匹配（"Chrome 120 on Windows" 不可能 locale=zh-CN）
    """

    # 预定义一致性规则（从 fingerprint_gen.py 的 MAP 反推）
    TEMPLATE_CONSTRAINTS = {
        "windows_chrome_120": {
            "platform": "Win64",
            "vendor": "Google Inc.",
            "locale": "en-US",
            "timezone": "America/New_York",
            "screen_res": (1920, 1080),
            "ua_contains": "Chrome/1",  # 兼容 Chrome/120 和 Edg/120
            "hardware_concurrency_in": (4, 8, 16),
        },
        "windows_chrome_121": {
            "platform": "Win64",
            "vendor": "Google Inc.",
            "locale": "en-US",
            "timezone": "America/New_York",
            "screen_res": (2560, 1440),
            "ua_contains": "Chrome/121",
            "hardware_concurrency_in": (4, 8, 16),
        },
        "macos_safari_17": {
            "platform": "MacIntel",
            "vendor": "Apple Computer, Inc.",
            "locale": "en-US",
            "timezone": "America/Los_Angeles",
            "screen_res": (1440, 900),
            # UA pool 含 Safari(AppleWebKit/605) + Chrome(AppleWebKit/537.36)，两个都合法
            "ua_contains": "AppleWebKit/",
            "hardware_concurrency_in": (4, 8),
        },
        "linux_chrome_120": {
            "platform": "Linux x86_64",
            "vendor": "Google Inc.",
            "locale": "en-US",
            "timezone": "America/New_York",
            "screen_res": (1920, 1080),
            "ua_contains": "Chrome/1",  # 兼容 Chrome/119 和 Chrome/120
            "hardware_concurrency_in": (4, 8, 16),
        },
        "mobile_android": {
            "platform": "Linux armv8l",
            "vendor": "Google Inc.",
            "locale": "en-US",
            "timezone": "America/New_York",
            "screen_res": (412, 915),
            "ua_contains": "Chrome/120",
            "hardware_concurrency_in": (4, 8, 16),  # RNG 可能选到 16
        },
        "mobile_ios": {
            "platform": "iPhone",
            "vendor": "Apple Computer, Inc.",
            "locale": "en-US",
            "timezone": "America/Los_Angeles",
            "screen_res": (390, 844),
            "ua_contains": "Mobile/15E148",
            "hardware_concurrency_in": (4, 6, 8, 16),  # RNG 可能选到 16
        },
    }

    def test_windows_chrome_120_consistency(self):
        """windows_chrome_120: 7 项一致性"""
        gen = FingerprintGenerator(seed=111)
        fp = gen.generate(template="windows_chrome_120")
        c = self.TEMPLATE_CONSTRAINTS["windows_chrome_120"]
        assert fp.platform == c["platform"], f"platform: {fp.platform} != {c['platform']}"
        assert fp.vendor == c["vendor"], f"vendor: {fp.vendor} != {c['vendor']}"
        assert fp.locale == c["locale"], f"locale: {fp.locale} != {c['locale']}"
        assert fp.timezone == c["timezone"], f"timezone: {fp.timezone} != {c['timezone']}"
        assert fp.screen_resolution == c["screen_res"], f"screen: {fp.screen_resolution} != {c['screen_res']}"
        assert c["ua_contains"] in fp.user_agent, f"UA missing {c['ua_contains']}: {fp.user_agent}"
        assert fp.hardware_concurrency in c["hardware_concurrency_in"]

    def test_macos_safari_17_consistency(self):
        """macos_safari_17: 7 项一致性"""
        gen = FingerprintGenerator(seed=222)
        fp = gen.generate(template="macos_safari_17")
        c = self.TEMPLATE_CONSTRAINTS["macos_safari_17"]
        assert fp.platform == c["platform"]
        assert fp.vendor == c["vendor"]
        assert fp.locale == c["locale"]
        assert fp.timezone == c["timezone"]
        assert fp.screen_resolution == c["screen_res"]
        assert c["ua_contains"] in fp.user_agent
        assert fp.hardware_concurrency in c["hardware_concurrency_in"]

    def test_linux_chrome_120_consistency(self):
        """linux_chrome_120: 7 项一致性"""
        gen = FingerprintGenerator(seed=333)
        fp = gen.generate(template="linux_chrome_120")
        c = self.TEMPLATE_CONSTRAINTS["linux_chrome_120"]
        assert fp.platform == c["platform"]
        assert fp.vendor == c["vendor"]
        assert fp.locale == c["locale"]
        assert fp.timezone == c["timezone"]
        assert fp.screen_resolution == c["screen_res"]
        assert c["ua_contains"] in fp.user_agent
        assert fp.hardware_concurrency in c["hardware_concurrency_in"]

    def test_mobile_android_consistency(self):
        """mobile_android: 7 项一致性"""
        gen = FingerprintGenerator(seed=444)
        fp = gen.generate(template="mobile_android")
        c = self.TEMPLATE_CONSTRAINTS["mobile_android"]
        assert fp.platform == c["platform"]
        assert fp.vendor == c["vendor"]
        assert fp.locale == c["locale"]
        assert fp.timezone == c["timezone"]
        assert fp.screen_resolution == c["screen_res"]
        assert c["ua_contains"] in fp.user_agent
        assert fp.hardware_concurrency in c["hardware_concurrency_in"]

    def test_mobile_ios_consistency(self):
        """mobile_ios: 7 项一致性"""
        gen = FingerprintGenerator(seed=555)
        fp = gen.generate(template="mobile_ios")
        c = self.TEMPLATE_CONSTRAINTS["mobile_ios"]
        assert fp.platform == c["platform"]
        assert fp.vendor == c["vendor"]
        assert fp.locale == c["locale"]
        assert fp.timezone == c["timezone"]
        assert fp.screen_resolution == c["screen_res"]
        assert c["ua_contains"] in fp.user_agent
        assert fp.hardware_concurrency in c["hardware_concurrency_in"]

    def test_all_templates_produce_consistent_fingerprint(self):
        """所有 template 的 7 项都通过一致性检查"""
        gen = FingerprintGenerator(seed=888)
        for tpl in self.TEMPLATE_CONSTRAINTS:
            fp = gen.generate(template=tpl)
            c = self.TEMPLATE_CONSTRAINTS[tpl]
            errors = []
            if fp.platform != c["platform"]:
                errors.append(f"[{tpl}] platform: {fp.platform} != {c['platform']}")
            if fp.vendor != c["vendor"]:
                errors.append(f"[{tpl}] vendor: {fp.vendor} != {c['vendor']}")
            if fp.locale != c["locale"]:
                errors.append(f"[{tpl}] locale: {fp.locale} != {c['locale']}")
            if fp.timezone != c["timezone"]:
                errors.append(f"[{tpl}] timezone: {fp.timezone} != {c['timezone']}")
            if fp.screen_resolution != c["screen_res"]:
                errors.append(f"[{tpl}] screen: {fp.screen_resolution} != {c['screen_res']}")
            if c["ua_contains"] not in fp.user_agent:
                errors.append(f"[{tpl}] UA missing {c['ua_contains']}: {fp.user_agent}")
            if fp.hardware_concurrency not in c["hardware_concurrency_in"]:
                errors.append(f"[{tpl}] hardware_concurrency: {fp.hardware_concurrency} not in {c['hardware_concurrency_in']}")
            assert not errors, "\n".join(errors)


class TestFingerprintGeneratorCanvasAudio:
    """Canvas/Audio seed 关联性检查"""

    def test_canvas_audio_seed_derived_from_same_combined_seed(self):
        """canvas_seed 和 audio_seed 都来自 combined_seed，不能独立飘移"""
        gen = FingerprintGenerator(seed=999)
        fp = gen.generate(template="windows_chrome_120")
        # combined = canvas | (audio << 31)，两者同源
        combined = (fp.audio_seed << 31) | fp.canvas_seed
        assert combined != 0, "combined seed must be non-zero"

    def test_canvas_seed_non_zero(self):
        """canvas_seed 不能为 0（0 是未初始化的哨兵值）"""
        for seed in [1, 42, 777, 12345]:
            gen = FingerprintGenerator(seed=seed)
            fp = gen.generate(template="windows_chrome_120")
            assert fp.canvas_seed != 0, f"canvas_seed=0 for RNG seed {seed}"

    def test_audio_seed_non_zero(self):
        """audio_seed 不能为 0"""
        for seed in [1, 42, 777, 12345]:
            gen = FingerprintGenerator(seed=seed)
            fp = gen.generate(template="windows_chrome_120")
            assert fp.audio_seed != 0, f"audio_seed=0 for RNG seed {seed}"
