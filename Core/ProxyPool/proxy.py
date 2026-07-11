"""
Core/ProxyPool/proxy.py — 全局代理池的代理条目

全局代理池（Global ProxyPool）vs Profile 内嵌 proxy_pool：
- 全局：所有 Profile 共享一份代理（推荐），跨 Profile 复用率更高
- 内嵌：Profile.network.proxy_pool 列表（旧，向后兼容）

Proxy 数据类的字段：
  id: 唯一标识（如 "proxy-001"）
  url: 完整 URL 或 server-only（"http://host:port" 或 "socks5://user:pass@host:port"）
  proxy_type: http / https / socks5
  username/password: 显式认证（优先于 URL 内嵌）
  region: ISO 国家代码（CN/US/JP 等，给 geoip 配对）
  tags: 自定义标签（["residential", "datacenter"]）
  enabled: 是否启用
  notes: 备注
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

_URL_AUTH_RE = re.compile(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*)://((?P<user>[^:@]+):(?P<pass>[^@]+)@)?(?P<host>[^/@]+)(?P<path>/.*)?$")


@dataclass
class Proxy:
    """全局代理池中的单个代理条目。

    字段约束：
      - id 自动生成（用户传空字符串时）
      - url 必须能 parse 出 scheme + host（host 可带端口）
      - proxy_type 限定 http/https/socks5
    """
    id: str = ""
    url: str = ""
    proxy_type: str = "http"  # http | https | socks5
    username: Optional[str] = None
    password: Optional[str] = None
    region: Optional[str] = None  # ISO 3166-1 alpha-2 (CN/US/JP/...)
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    notes: str = ""

    # ─── 持久化 ────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "proxy_type": self.proxy_type,
            "username": self.username,
            "password": self.password,
            "region": self.region,
            "tags": list(self.tags),
            "enabled": self.enabled,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Proxy":
        kwargs = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**kwargs)

    # ─── 派生属性 ──────────────────────────────────────────────

    def parsed_scheme(self) -> Optional[str]:
        """从 URL 解析 scheme（http/https/socks5）。

        解析失败返回 None。
        """
        if not self.url:
            return None
        m = _URL_AUTH_RE.match(self.url)
        if not m:
            return None
        return m.group("scheme").lower()

    def parsed_host_port(self) -> Optional[str]:
        """从 URL 解析 host:port（不含 scheme 和认证）。"""
        if not self.url:
            return None
        m = _URL_AUTH_RE.match(self.url)
        if not m:
            return None
        host = m.group("host")
        # host 可能已经含端口或不含
        return host

    def parsed_username(self) -> Optional[str]:
        """获取最终生效的 username（URL 内嵌 > 显式字段）。"""
        if self.username:
            return self.username
        if not self.url:
            return None
        m = _URL_AUTH_RE.match(self.url)
        if not m:
            return None
        return m.group("user")

    def parsed_password(self) -> Optional[str]:
        """获取最终生效的 password（URL 内嵌 > 显式字段）。"""
        if self.password:
            return self.password
        if not self.url:
            return None
        m = _URL_AUTH_RE.match(self.url)
        if not m:
            return None
        return m.group("pass")

    def get_playwright_proxy(self) -> Optional[tuple]:
        """转换为 Playwright proxy 三元组 (server, username, password)。

        解析优先级：
          1. url 内嵌认证
          2. 显式 username/password 字段
        """
        if not self.url:
            return None
        m = _URL_AUTH_RE.match(self.url)
        if not m:
            return None
        scheme = m.group("scheme")
        host = m.group("host")
        server = f"{scheme}://{host}"
        username = self.parsed_username()
        password = self.parsed_password()
        return (server, username, password)

    # ─── 校验 ──────────────────────────────────────────────────

    def validate(self) -> None:
        """校验字段合法性。失败抛 ValueError。

        Checks:
          - url 非空 + scheme 合法
          - proxy_type ∈ {http, https, socks5}
          - 如果 url 是 socks5:// 则 proxy_type 可以是 socks5（一致即可）
        """
        if not self.url or not self.url.strip():
            raise ValueError(f"Proxy.url 不能为空（id={self.id!r}）")
        scheme = self.parsed_scheme()
        if not scheme:
            raise ValueError(
                f"Proxy.url 无法解析 scheme（id={self.id!r}, url={self.url!r}）"
            )
        if scheme not in ("http", "https", "socks5", "socks5h"):
            raise ValueError(
                f"Proxy.url scheme 必须是 http/https/socks5（id={self.id!r}, scheme={scheme!r}）"
            )
        if self.proxy_type not in ("http", "https", "socks5"):
            raise ValueError(
                f"Proxy.proxy_type 必须是 http/https/socks5（id={self.id!r}, type={self.proxy_type!r}）"
            )
        if self.region and len(self.region) != 2:
            raise ValueError(
                f"Proxy.region 必须是 ISO 3166-1 alpha-2 双字母代码（id={self.id!r}, region={self.region!r}）"
            )

    # ─── 标识生成 ──────────────────────────────────────────────

    @staticmethod
    def make_id(prefix: str = "proxy") -> str:
        """生成 8 字符短 ID（profile_manager 风格一致）。"""
        return f"{prefix}-{uuid.uuid4().hex[:6]}"

    def __post_init__(self):
        if not self.id:
            self.id = self.make_id()

    # 简易属性：方便 UI 展示
    @property
    def display_name(self) -> str:
        host = self.parsed_host_port() or self.url
        return f"{self.id} ({host})"