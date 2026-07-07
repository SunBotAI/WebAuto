"""
Core/Profile/fingerprint_gen.py — 指纹生成器

目标：生成"统计一致"的真实浏览器指纹。
同一 hardware 配置 + 同一 seed → 相同的 Canvas/WebGL/Audio 噪声输出。
"""

from __future__ import annotations

import random
import hashlib
from typing import Optional, List, Dict
from .profile import FingerprintConfig


# ─── 真实浏览器统计分布（用于生成"看起来真实"的指纹）────────────────────────

# 常见 UA 池（按 OS 分组）
UA_TEMPLATES = {
    "windows_chrome_120": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    ],
    "windows_chrome_121": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    ],
    "macos_safari_17": [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ],
    "linux_chrome_120": [
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    ],
    "mobile_android": [
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    ],
    "mobile_ios": [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    ],
}

PLATFORM_MAP = {
    "windows_chrome_120": "Win64",
    "windows_chrome_121": "Win64",
    "macos_safari_17": "MacIntel",
    "linux_chrome_120": "Linux x86_64",
    "mobile_android": "Linux armv8l",
    "mobile_ios": "iPhone",
}

VENDOR_MAP = {
    "windows_chrome_120": "Google Inc.",
    "windows_chrome_121": "Google Inc.",
    "macos_safari_17": "Apple Computer, Inc.",
    "linux_chrome_120": "Google Inc.",
    "mobile_android": "Google Inc.",
    "mobile_ios": "Apple Computer, Inc.",
}

TIMEZONE_MAP = {
    "windows_chrome_120": "America/New_York",
    "windows_chrome_121": "America/New_York",
    "macos_safari_17": "America/Los_Angeles",
    "linux_chrome_120": "America/New_York",
    "mobile_android": "America/New_York",
    "mobile_ios": "America/Los_Angeles",
}

LOCALE_MAP = {
    "windows_chrome_120": "en-US",
    "windows_chrome_121": "en-US",
    "macos_safari_17": "en-US",
    "linux_chrome_120": "en-US",
    "mobile_android": "en-US",
    "mobile_ios": "en-US",
}

SCREEN_RESOLUTION_MAP = {
    "windows_chrome_120": (1920, 1080),
    "windows_chrome_121": (2560, 1440),
    "macos_safari_17": (1440, 900),
    "linux_chrome_120": (1920, 1080),
    "mobile_android": (412, 915),
    "mobile_ios": (390, 844),
}

# 常见的插件列表（真实 Chrome 有 5 个左右）
REALISTIC_PLUGINS = [
    {"name": "Chrome PDF Plugin", "description": "Portable Document Format",
     "filename": "internal-pdf-viewer"},
    {"name": "Chrome PDF Viewer", "description": "",
     "filename": "mhjfbmdgcfjbbpaeojofohoefgiehjai"},
    {"name": "Native Client", "description": "",
     "filename": "internal-nacl-plugin"},
    {"name": "Chrome Quick Share", "description": "",
     "filename": "quick-share"},
]

REALISTIC_FONTS = {
    "windows_chrome_120": ["Arial", "Calibri", "Times New Roman", "Courier New", "Segoe UI"],
    "macos_safari_17": ["Helvetica", "Arial", "Times New Roman", "Courier New"],
    "linux_chrome_120": ["Liberation Sans", "DejaVu Sans", "Ubuntu", "Times New Roman"],
    "mobile_android": ["Roboto", "sans-serif"],
    "mobile_ios": ["Helvetica Neue", "Arial", "sans-serif"],
}


class FingerprintGenerator:
    """
    生成统计一致的浏览器指纹。

    核心约束：
    - UA、platform、vendor、locale、timezone 必须相互匹配（"Chrome 120 on Windows" 不可能 locale=zh-CN）
    - Canvas seed、WebGL seed、Audio seed 必须来自同一 PRNG（保证同一 Profile 的 Canvas hash 稳定）
    - Plugins 数量和 mimeTypes 数量匹配
    """

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def generate(self, template: Optional[str] = None) -> FingerprintConfig:
        """
        生成一个完整指纹。

        Args:
            template: "windows_chrome_120" | "macos_safari_17" | "linux_chrome_120"
                      | "mobile_android" | "mobile_ios" | None（随机选）

        Returns:
            FingerprintConfig（已初始化 canvas_seed / audio_seed）
        """
        if template is None:
            template = self.rng.choice(list(UA_TEMPLATES.keys()))

        if template not in UA_TEMPLATES:
            raise ValueError(f"Unknown template: {template}. Available: {list(UA_TEMPLATES.keys())}")

        # UA
        ua = self.rng.choice(UA_TEMPLATES[template])

        # 生成关联 seed（保证 Canvas / WebGL / Audio 一致）
        raw_seed = self.rng.getrandbits(64)
        combined = int.from_bytes(
            hashlib.sha256(raw_seed.to_bytes(8, "big") + template.encode()).digest()[:8],
            "big",
        )
        canvas_seed = combined & 0x7FFFFFFF
        audio_seed = (combined >> 31) & 0x7FFFFFFF

        # Plugins
        plugins = REALISTIC_PLUGINS[:self.rng.randint(3, 4)]

        return FingerprintConfig(
            user_agent=ua,
            platform=PLATFORM_MAP.get(template, "Linux x86_64"),
            vendor=VENDOR_MAP.get(template, "Google Inc."),
            locale=LOCALE_MAP.get(template, "en-US"),
            timezone=TIMEZONE_MAP.get(template, "America/New_York"),
            screen_resolution=SCREEN_RESOLUTION_MAP.get(template, (1920, 1080)),
            color_depth=24,
            hardware_concurrency=self.rng.choice([4, 8, 16]),
            device_memory=self.rng.choice([4, 8, 16]),
            canvas_seed=canvas_seed,
            webgl_vendor="Intel Inc.",
            webgl_renderer="Intel Iris OpenGL Engine",
            audio_seed=audio_seed,
            plugins=plugins,
            fonts=REALISTIC_FONTS.get(template, REALISTIC_FONTS["linux_chrome_120"]),
            webdriver=False,
            headless_sanitize=True,
        )

    def mutate(self, fp: FingerprintConfig, *, keep_seed: bool = True) -> FingerprintConfig:
        """
        基于已有指纹微调（改 UA 但保留 canvas_seed，保持指纹稳定性）。

        Args:
            fp: 原始指纹
            keep_seed: True = 保留原 seed（只换 UA/platform 等）；False = 重新生成 seed
        """
        d = fp.to_dict()
        d.pop("screen_resolution")
        new_fp = FingerprintConfig.from_dict({"screen_resolution": list(fp.screen_resolution), **d})

        if not keep_seed:
            new_fp.canvas_seed = self.rng.randint(0, 2**31 - 1)
            new_fp.audio_seed = self.rng.randint(0, 2**31 - 1)
        return new_fp

    @staticmethod
    def from_real_browser(profile_json_path: str) -> FingerprintConfig:
        """
        从真实浏览器导出的 profile.json 导入（AdsPower / GoLogin 兼容格式）。
        预留接口，暂未实现。
        """
        import json
        with open(profile_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # TODO: 解析 AdsPower/GoLogin 格式，映射到 FingerprintConfig
        raise NotImplementedError("from_real_browser: 解析器待实现")
