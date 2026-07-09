"""
Core/Profile/profile.py — Profile 数据模型

Profile = 一个完整的账号配置单元
包含：指纹(FingerprintConfig) + 网络(NetworkConfig) + 标签 + 状态 + 持久化路径
"""

from __future__ import annotations

import uuid
import random
import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any


class ProfileStatus(Enum):
    """Profile 生命周期状态"""
    READY = "ready"          # 已配置可启动
    RUNNING = "running"      # 正在使用中
    COOLDOWN = "cooldown"    # 暂时休息 (防风控)
    BANNED = "banned"        # 已封禁
    ARCHIVED = "archived"    # 归档不再用


@dataclass
class NetworkConfig:
    """代理 + 网络配置"""
    proxy_url: Optional[str] = None              # "http://user:pass@host:port" 或 "http://host:port"
    proxy_username: Optional[str] = None          # 住宅代理认证用户名（优先于 URL 内嵌）
    proxy_password: Optional[str] = None          # 住宅代理认证密码（优先于 URL 内嵌）
    proxy_type: str = "http"                     # http | socks5
    geoip_country: Optional[str] = None          # "US" | "CN" | ...
    dns_over_https: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NetworkConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def get_playwright_proxy(self) -> Optional[tuple]:
        """
        返回 Playwright proxy 配置的三元组 (server, username, password)。

        解析优先级：
        1. proxy_url 内嵌认证（http://user:pass@host:port）
        2. 显式 proxy_username / proxy_password 字段
        """
        if not self.proxy_url:
            return None

        # 先尝试从 URL 内嵌解析
        url = self.proxy_url
        username: Optional[str] = None
        password: Optional[str] = None

        if "://" in url:
            scheme, rest = url.split("://", 1)
            if "@" in rest:
                credentials, host_port = rest.rsplit("@", 1)
                if ":" in credentials:
                    username, password = credentials.split(":", 1)
                # URL 内嵌优先；若显式字段也有值，显式字段覆盖
                if self.proxy_username is not None:
                    username = self.proxy_username
                if self.proxy_password is not None:
                    password = self.proxy_password
                # 重构为无认证的 server URL
                server = f"{scheme}://{host_port}"
            else:
                server = url
                if self.proxy_username is not None:
                    username = self.proxy_username
                if self.proxy_password is not None:
                    password = self.proxy_password
        else:
            server = url
            username = self.proxy_username
            password = self.proxy_password

        return (server, username, password)


@dataclass
class FingerprintConfig:
    """浏览器指纹配置"""
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    platform: str = "Linux x86_64"
    vendor: str = "Google Inc."
    locale: str = "en-US"
    timezone: str = "America/New_York"
    screen_resolution: tuple = (1920, 1080)
    color_depth: int = 24
    hardware_concurrency: int = 8
    device_memory: int = 8
    canvas_seed: int = 0
    webgl_vendor: str = "Intel Inc."
    webgl_renderer: str = "Intel Iris OpenGL Engine"
    audio_seed: int = 0
    plugins: List[Dict] = field(default_factory=list)
    fonts: List[str] = field(default_factory=list)
    webdriver: bool = False
    headless_sanitize: bool = True

    # 内部方法：自动生成 seed（延迟初始化）
    def _ensure_seeds(self) -> None:
        """确保 canvas_seed 和 audio_seed 已初始化"""
        if self.canvas_seed == 0:
            self.canvas_seed = random.randint(0, 2**31 - 1)
        if self.audio_seed == 0:
            self.audio_seed = random.randint(0, 2**31 - 1)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["screen_resolution"] = list(d["screen_resolution"])
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "FingerprintConfig":
        if "screen_resolution" in data and isinstance(data["screen_resolution"], list):
            data = dict(data)
            data["screen_resolution"] = tuple(data["screen_resolution"])
        kwargs = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**kwargs)

    def get_anti_detect_seed(self) -> int:
        """返回用于 AntiDetect 的稳定 seed"""
        self._ensure_seeds()
        return self.canvas_seed


@dataclass
class Profile:
    """
    完整的账号配置单元 = 指纹 + 网络 + 标签 + 状态

    用户业务以"账号"为单位，一个账号 = 一个 FingerprintConfig + 一个 NetworkConfig
    + 一组 Cookie（通过 user_data_dir 隔离）+ 一批自定义脚本。
    跨 Profile 完全隔离。
    """
    id: str = ""
    name: str = ""
    tags: List[str] = field(default_factory=list)

    fingerprint: FingerprintConfig = field(default_factory=lambda: FingerprintConfig())
    network: NetworkConfig = field(default_factory=NetworkConfig)

    # 运行期状态
    status: ProfileStatus = ProfileStatus.READY
    cooldown_until: Optional[float] = None   # unix 时间戳
    last_used: Optional[float] = None

    # 持久化路径（由 ProfileStore 分配）
    storage_dir: Optional[Path] = None

    # 启动参数
    browser_args: List[str] = field(default_factory=list)
    extensions: List[str] = field(default_factory=list)
    custom_scripts: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]
        if not self.name:
            self.name = self.id
        # 确保 seed 已初始化
        self.fingerprint._ensure_seeds()

    # ─── 持久化 ────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化（用于 YAML / JSON）"""
        return {
            "id": self.id,
            "name": self.name,
            "tags": self.tags,
            "status": self.status.value,
            "cooldown_until": self.cooldown_until,
            "last_used": self.last_used,
            "storage_dir": str(self.storage_dir) if self.storage_dir else None,
            "fingerprint": self.fingerprint.to_dict(),
            "network": self.network.to_dict(),
            "browser_args": self.browser_args,
            "extensions": self.extensions,
            "custom_scripts": self.custom_scripts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        """反序列化"""
        fp_data = data.pop("fingerprint", {})
        net_data = data.pop("network", {})
        status_val = data.pop("status", "ready")
        storage_val = data.pop("storage_dir", None)

        kwargs = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        if "status" in data or "status" not in kwargs:
            kwargs["status"] = ProfileStatus(status_val) if status_val else ProfileStatus.READY
        if storage_val:
            kwargs["storage_dir"] = Path(storage_val)

        profile = cls(
            fingerprint=FingerprintConfig.from_dict(fp_data),
            network=NetworkConfig.from_dict(net_data),
            **kwargs,
        )
        return profile

    # ─── 业务方法 ──────────────────────────────────────────────

    def get_user_data_dir(self) -> Path:
        """返回该 Profile 的 Chromium User Data Directory"""
        if self.storage_dir is None:
            raise ValueError(f"Profile {self.id} has no storage_dir (not persisted?)")
        return self.storage_dir / "user-data"

    def get_meta_path(self) -> Path:
        """返回 meta.json 路径"""
        if self.storage_dir is None:
            raise ValueError(f"Profile {self.id} has no storage_dir")
        return self.storage_dir / "meta.json"

    def is_cooldown_active(self) -> bool:
        """当前是否处于 cooldown 状态"""
        if self.status != ProfileStatus.COOLDOWN:
            return False
        if self.cooldown_until is None:
            return False
        import time
        return time.time() < self.cooldown_until

    def apply_to_antidetect(self, cfg: "AntiDetectConfig") -> None:
        """
        把 fingerprint 同步到 AntiDetectConfig（7 项全量同步）。

        确保 Profile 级别的 canvas_seed 强制覆盖 AntiDetect 的 seed，
        并且 locale / timezone / screen / hardwareConcurrency 等也同步到 AntiDetectConfig
       （供 JS 注入脚本读取，实现真正的跨启动一致性）。

        同步的 7 项：
        1. fingerprint_seed → cfg.fingerprint_seed（Canvas/WebGL/Audio seed）
        2. locale          → cfg.navigator_locale（navigator.language）
        3. timezone        → cfg.timezone（Intl.DateTimeFormat）
        4. platform        → cfg.navigator_platform（navigator.platform）
        5. vendor          → cfg.webgl_vendor（WebGL UNMASKED_VENDOR_WEBGL）
        6. screen_resolution → cfg.screen_width / cfg.screen_height
        7. hardware_concurrency → cfg.hardware_concurrency
        """
        cfg.fingerprint_seed = self.fingerprint.get_anti_detect_seed()

        # T-011: 7 项字段同步
        cfg.navigator_locale = self.fingerprint.locale
        cfg.timezone = self.fingerprint.timezone
        cfg.navigator_platform = self.fingerprint.platform
        cfg.webgl_vendor = self.fingerprint.vendor
        cfg.screen_width, cfg.screen_height = self.fingerprint.screen_resolution
        cfg.hardware_concurrency = self.fingerprint.hardware_concurrency
        cfg.device_memory = self.fingerprint.device_memory

    # ─── ban / archive / restore ───────────────────────────────

    def ban(self, store: "ProfileStore" = None) -> None:
        """
        标记为 BANNED（风控封禁）。

        封禁后：
        - ProfilePool._is_available() 会拒绝借出
        - 状态持久化（传 store 则调用 store.save()，否则只改内存）
        - 如果正在被 pool 持有，下一次 release() 会发现状态异常（由调用方负责释放）
        """
        self.status = ProfileStatus.BANNED
        if store is not None:
            store.save(self)

    def archive(self, store: "ProfileStore" = None) -> None:
        """
        归档 Profile（不删除数据）。

        归档后：
        - ProfilePool._is_available() 会拒绝借出
        - 不占用 active 槽位
        - 数据保留在 storage_dir，可通过 restore() 恢复
        """
        self.status = ProfileStatus.ARCHIVED
        if store is not None:
            store.save(self)

    def restore(self, store: "ProfileStore" = None) -> None:
        """
        恢复 BANNED / ARCHIVED Profile 到 READY 状态。

        恢复后 Profile 可重新被 ProfilePool 借出。
        """
        if self.status not in (ProfileStatus.BANNED, ProfileStatus.ARCHIVED):
            raise ValueError(f"Profile {self.id} is {self.status.value}, not banned/archived")
        self.status = ProfileStatus.READY
        if store is not None:
            store.save(self)
