"""
Core/Profile — 指纹浏览器核心模块

Profile = 指纹 + 网络 + 标签 + 状态
所有上层业务（Spider / 抢购 / MCP）通过 Profile 层与底层浏览器交互。

子模块：
- profile.py      : Profile 数据类 + FingerprintConfig + NetworkConfig
- fingerprint_gen : 指纹生成器（Canvas/WebGL/Audio seed）
- store.py        : 本地持久化（CRUD + import/export）
- orchestrator.py : 浏览器编排器（生命周期管理）
- pool.py         : Profile 池（借/还/轮换策略）
"""

from .profile import Profile, FingerprintConfig, NetworkConfig, ProfileStatus
from .fingerprint_gen import FingerprintGenerator
from .store import ProfileStore
from .orchestrator import BrowserOrchestrator
from .pool import ProfilePool, AcquireStrategy

__all__ = [
    "Profile",
    "FingerprintConfig",
    "NetworkConfig",
    "ProfileStatus",
    "FingerprintGenerator",
    "ProfileStore",
    "BrowserOrchestrator",
    "ProfilePool",
    "AcquireStrategy",
]
