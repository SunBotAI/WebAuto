"""BrowserProfile 数据类。

字段约束:
    - fingerprint_seed: int, [0, 2**31-1],决定 Canvas / WebGL / Audio 噪声种子
    - hardware:         一组 (cores, memGB, dpr, screenW, screenH, colorDepth)
                        同 profile 内稳定,跨 session 跨重启持久化
    - viewport:         Playwright new_context(viewport=...) 用
    - locale:           zh-CN / en-US 等
    - timezone_id:      Asia/Shanghai / UTC 等
    - user_agent:       完整 UA 字符串
    - accept_language:  Accept-Language header 值

注意: 不存任何敏感数据(token / cookie / ip)。
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

_VALID_LOCALES = ("zh-CN", "en-US", "en-GB", "ja-JP")
_VALID_TZ = (
    "Asia/Shanghai", "Asia/Tokyo", "Asia/Hong_Kong",
    "America/New_York", "America/Los_Angeles", "Europe/London", "UTC",
)


@dataclass
class HardwareConsistent:
    """一组硬件值,用于覆盖 navigator.hardware* / screen / devicePixelRatio。

    选 (cores, memoryGB, dpr, screenW, screenH, colorDepth) 6 元组。
    所有值在 profile 创建时一次选定,后续 apply 到浏览器不该再变。
    """
    cores:       int = 8
    memory_gb:   int = 8
    dpr:         float = 1.0
    screen_w:    int = 1920
    screen_h:    int = 1080
    color_depth: int = 24

    def __post_init__(self):
        if self.cores not in (4, 8, 12, 16):
            raise ValueError(f"cores 应在 {{4,8,12,16}}, got {self.cores}")
        if self.memory_gb not in (4, 8, 16):
            raise ValueError(f"memory_gb 应在 {{4,8,16}}, got {self.memory_gb}")
        if self.dpr not in (1, 1.25, 1.5, 2):
            raise ValueError(f"dpr 应在 {{1, 1.25, 1.5, 2}}, got {self.dpr}")
        if not (1024 <= self.screen_w <= 3840):
            raise ValueError(f"screen_w 不合理: {self.screen_w}")
        if not (720 <= self.screen_h <= 2160):
            raise ValueError(f"screen_h 不合理: {self.screen_h}")
        if self.color_depth not in (24, 32):
            raise ValueError(f"color_depth 应为 24 / 32, got {self.color_depth}")


@dataclass
class ViewportConfig:
    """Playwright new_context 的 viewport 参数。

    与 HardwareConsistent.screen_* 解耦 -- 浏览器 viewport 是用户能看到的窗口大小,
    screen_* 是显示器物理分辨率。两者可以不同(用户开一个小窗口)。
    """
    width:  int = 1920
    height: int = 1080

    def __post_init__(self):
        if not (1024 <= self.width <= 3840):
            raise ValueError(f"viewport.width 不合理: {self.width}")
        if not (720 <= self.height <= 2160):
            raise ValueError(f"viewport.height 不合理: {self.height}")


@dataclass
class BrowserProfile:
    """一份完整的浏览器指纹配置,可序列化到 JSON 持久化。"""
    profile_id:        str
    label:             str = ""
    fingerprint_seed:  int = 0
    hardware:          HardwareConsistent = field(default_factory=HardwareConsistent)
    viewport:           ViewportConfig    = field(default_factory=ViewportConfig)
    locale:             str               = "zh-CN"
    timezone_id:        str               = "Asia/Shanghai"
    user_agent:         str               = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    accept_language:    str = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    color_scheme:       str = "light"
    created_at:         Optional[str] = None
    updated_at:         Optional[str] = None

    def __post_init__(self):
        if self.fingerprint_seed < 0 or self.fingerprint_seed >= 2**31:
            raise ValueError(
                f"fingerprint_seed 应在 [0, 2**31), got {self.fingerprint_seed}"
            )
        if self.locale not in _VALID_LOCALES:
            import warnings
            warnings.warn(f"locale 罕见: {self.locale}", stacklevel=2)
        if self.timezone_id not in _VALID_TZ:
            import warnings
            warnings.warn(f"timezone_id 罕见: {self.timezone_id}", stacklevel=2)
        if self.color_scheme not in ("light", "dark", "no-preference"):
            raise ValueError(f"color_scheme 应是 light/dark/no-preference")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BrowserProfile":
        kwargs = dict(d)
        hw = kwargs.pop("hardware", None) or {}
        kwargs["hardware"] = HardwareConsistent(**hw) if isinstance(hw, dict) else hw
        vp = kwargs.pop("viewport", None) or {}
        kwargs["viewport"] = ViewportConfig(**vp) if isinstance(vp, dict) else vp
        return cls(**kwargs)

    def apply_to_anti_detect_config(self, cfg) -> None:
        """把 profile 字段写进 AntiDetectConfig 的 fingerprint_seed 字段。

        AntiDetect 的其他 hook (canvas noise / WebGL vendor 等) 都是
        基于 fingerprint_seed 派生,所以把 seed 写进去,Canvas / WebGL / Audio 噪声就一致了。
        hardware 字段没有给 AntiDetect 用 -- 它由 Playwright 启动参数传 --
        所以 apply_to_anti_detect_config 只写 seed;硬件一致需要 Playwright 启动参数配合。
        """
        cfg.fingerprint_seed = int(self.fingerprint_seed)

    def apply_to_playwright_kwargs(self) -> Dict[str, Any]:
        return {
            "viewport":     {"width": self.viewport.width, "height": self.viewport.height},
            "locale":       self.locale,
            "timezone_id":  self.timezone_id,
            "user_agent":   self.user_agent,
            "color_scheme": self.color_scheme,
        }

    def apply_to_http_headers(self) -> Dict[str, str]:
        return {
            "User-Agent":          self.user_agent,
            "Accept-Language":     self.accept_language,
            "sec-ch-ua":           '"Not.A/Brand";v="24", "Chromium";v="120"',
            "sec-ch-ua-mobile":    "?0",
            "sec-ch-ua-platform":  '"Windows"',
        }
