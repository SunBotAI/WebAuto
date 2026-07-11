"""
Core/Profile/proxy_rotator.py — 代理健康追踪 + 失败轮换

核心语义：
- Profile 持有多个代理 URL（proxy_pool）
- 每次 HTTP 失败 → consecutive_failures++
- 连续 N 次失败 → 该代理 cooldown T 分钟 + 自动切换到下一个代理
- 全部轮换完仍失败 → Profile 进入 BANNED

用法：
    from Core.Profile.proxy_rotator import ProxyRotator, ProxyPolicy

    rotator = ProxyRotator(default_max_failures=3, cooldown_minutes=30)

    # Profile 借出时注册
    rotator.register("profile-abc", proxy_pool=[
        "http://user1:pass1@proxy1.example.com:8080",
        "http://user2:pass2@proxy2.example.com:8080",
    ])

    # HTTP 失败时调用
    rotator.on_failure("profile-abc")

    # 获取当前代理（失败后自动切换）
    proxy_url = rotator.get_current_proxy("profile-abc")

    # HTTP 成功时调用（重置计数器）
    rotator.on_success("profile-abc")

    # 查看状态
    status = rotator.get_status("profile-abc")
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ProxyState(Enum):
    ACTIVE = "active"          # 正常可用
    COOLDOWN = "cooldown"      # 临时冷却中
    BANNED = "banned"         # 已废弃（全部轮换完仍失败）


@dataclass
class ProxyEntry:
    """单个代理的健康状态"""
    url: str
    state: ProxyState = ProxyState.ACTIVE
    consecutive_failures: int = 0
    cooldown_until: Optional[float] = None   # unix timestamp
    region: Optional[str] = None             # ISO 国家代码（CN/US/JP...）

    def is_available(self) -> bool:
        if self.state == ProxyState.BANNED:
            return False
        if self.state == ProxyState.COOLDOWN:
            if self.cooldown_until and time.time() >= self.cooldown_until:
                # cooldown 到期，自动恢复
                self.state = ProxyState.ACTIVE
                self.consecutive_failures = 0
                self.cooldown_until = None
                return True
            return False
        return True


class ProxyPolicy:
    """可配置的代理轮换策略"""

    def __init__(
        self,
        max_failures: int = 3,
        cooldown_minutes: float = 30.0,
        max_proxies_per_profile: int = 10,
    ):
        self.max_failures = max_failures          # 连续失败 N 次触发 cooldown
        self.cooldown_minutes = cooldown_minutes   # cooldown 时长（分钟）
        self.max_proxies_per_profile = max_proxies_per_profile


class ProxyRotator:
    """
    Profile 级别代理健康追踪 + 失败自动轮换。

    线程安全：所有状态操作走 threading.Lock（多线程 Playwright/CDP 场景需要）。

    集成方式（推荐）：
        1. BrowserOrchestrator.get_context() 失败后 → rotator.on_failure(profile.id)
        2. Pool.release() 时可选 → rotator.reset(profile.id)
    """

    def __init__(self, policy: Optional[ProxyPolicy] = None):
        self._policy = policy or ProxyPolicy()
        self._lock = threading.RLock()
        # profile_id → list[ProxyEntry]
        self._proxy_pools: dict[str, list[ProxyEntry]] = {}
        # profile_id → 当前使用的 proxy index
        self._current_index: dict[str, int] = {}
        # profile_id → consecutive_failures（整体，不针对某个 proxy）
        self._profile_failures: dict[str, int] = {}

    # ─── 注册 / 注销 ──────────────────────────────────────────

    def register(self, profile_id: str, proxy_pool: list[str]) -> None:
        """
        为 Profile 注册代理池。

        Args:
            profile_id:   Profile ID
            proxy_pool:   代理 URL 列表（http://user:pass@host:port 格式）
        """
        with self._lock:
            entries = [ProxyEntry(url=url) for url in proxy_pool[:self._policy.max_proxies_per_profile]]
            self._proxy_pools[profile_id] = entries
            self._current_index[profile_id] = 0
            self._profile_failures[profile_id] = 0

    def unregister(self, profile_id: str) -> None:
        """注销 Profile 的代理状态（调用时须在 lock 外层）"""
        with self._lock:
            self._proxy_pools.pop(profile_id, None)
            self._current_index.pop(profile_id, None)
            self._profile_failures.pop(profile_id, None)

    # ─── 状态查询 ──────────────────────────────────────────────

    def get_current_proxy(self, profile_id: str) -> Optional[str]:
        """
        返回 Profile 当前应该使用的代理 URL。

        自动跳过 cooldown / banned 的代理，返回下一个可用代理。
        若全部不可用，返回 None（触发 BANNED 流程）。
        """
        with self._lock:
            pool = self._proxy_pools.get(profile_id)
            if not pool:
                return None

            # 找当前可用的
            start_idx = self._current_index.get(profile_id, 0)
            n = len(pool)

            for offset in range(n):
                idx = (start_idx + offset) % n
                entry = pool[idx]
                if entry.is_available():
                    if offset > 0:
                        # 发生了轮换，更新 index
                        self._current_index[profile_id] = idx
                        logger.info(
                            "[ProxyRotator] profile=%s rotated to proxy[%d]=%s",
                            profile_id, idx, entry.url,
                        )
                    return entry.url

            # 全部不可用
            return None

    def get_status(self, profile_id: str) -> dict:
        """返回 Profile 代理健康状态快照（用于调试）"""
        with self._lock:
            pool = self._proxy_pools.get(profile_id, [])
            return {
                "profile_id": profile_id,
                "current_index": self._current_index.get(profile_id),
                "profile_consecutive_failures": self._profile_failures.get(profile_id, 0),
                "proxies": [
                    {
                        "url": e.url,
                        "state": e.state.value,
                        "consecutive_failures": e.consecutive_failures,
                        "cooldown_until": e.cooldown_until,
                        "available": e.is_available(),
                    }
                    for e in pool
                ],
            }

    # ─── 事件回调 ──────────────────────────────────────────────

    def on_success(self, profile_id: str) -> None:
        """
        HTTP 成功时调用：重置失败计数器。

        调用时机（建议）：
            response.ok → rotator.on_success(profile.id)
        """
        with self._lock:
            self._profile_failures[profile_id] = 0
            pool = self._proxy_pools.get(profile_id)
            if pool:
                idx = self._current_index.get(profile_id, 0) % len(pool)
                pool[idx].consecutive_failures = 0
                pool[idx].state = ProxyState.ACTIVE

    def on_failure(self, profile_id: str) -> Optional[str]:
        """
        HTTP 失败时调用：计数 + 触发轮换。

        Returns:
            切换后的新代理 URL；若已全部轮换完仍失败，返回 None（调用方应 ban profile）。

        调用时机（建议）：
            except HTTPError / asyncio.TimeoutError →
                rotator.on_failure(profile.id)
        """
        with self._lock:
            self._profile_failures[profile_id] = self._profile_failures.get(profile_id, 0) + 1
            pool = self._proxy_pools.get(profile_id, [])
            if not pool:
                return None

            idx = self._current_index.get(profile_id, 0) % len(pool)
            entry = pool[idx]
            entry.consecutive_failures += 1

            logger.warning(
                "[ProxyRotator] profile=%s proxy[%d] failure #%d (threshold=%d)",
                profile_id, idx, entry.consecutive_failures, self._policy.max_failures,
            )

            # 判断是否触发 cooldown
            if entry.consecutive_failures >= self._policy.max_failures:
                return self._cooldown_and_rotate(profile_id, idx)

            return entry.url

    # ─── 内部 ──────────────────────────────────────────────────

    def _cooldown_and_rotate(self, profile_id: str, bad_idx: int) -> Optional[str]:
        """
        1. 当前代理进入 cooldown
        2. 寻找下一个可用代理
        3. 返回新代理 URL；若全部 cooldown（未到 BANNED 终态），返回 None（调用方应 ban profile）
        """
        pool = self._proxy_pools[profile_id]
        bad_entry = pool[bad_idx]

        # cooldown
        bad_entry.state = ProxyState.COOLDOWN
        bad_entry.cooldown_until = time.time() + self._policy.cooldown_minutes * 60
        logger.warning(
            "[ProxyRotator] profile=%s proxy[%d]=%s entering cooldown for %.0f min",
            profile_id, bad_idx, bad_entry.url, self._policy.cooldown_minutes,
        )

        # 找下一个可用代理
        n = len(pool)
        for offset in range(1, n):
            next_idx = (bad_idx + offset) % n
            next_entry = pool[next_idx]
            if next_entry.is_available():
                self._current_index[profile_id] = next_idx
                logger.info(
                    "[ProxyRotator] profile=%s switched to proxy[%d]=%s",
                    profile_id, next_idx, next_entry.url,
                )
                return next_entry.url

        # 全部 cooldown 或 banned → 返回 None（不自动 BANNED，
        # 让 cooldown 自然到期后 get_current_proxy 恢复可用）
        logger.warning(
            "[ProxyRotator] profile=%s all proxies in cooldown/banned, waiting recovery",
            profile_id,
        )
        return None

    def reset(self, profile_id: str) -> None:
        """
        重置 Profile 的失败计数（归还 Pool 时调用）。
        不改变代理池和当前 index。
        """
        with self._lock:
            self._profile_failures[profile_id] = 0
            pool = self._proxy_pools.get(profile_id)
            if pool:
                for entry in pool:
                    entry.consecutive_failures = 0
