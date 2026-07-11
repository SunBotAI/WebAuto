"""
Tools/proxy_backend.py — T-072 代理 CRUD + health 报表 + 批量启用/禁用 + 失效剔除

对外暴露的纯函数（无状态单例）：
    register_proxies(profile_id, proxy_urls)    → bool
    unregister_proxies(profile_id)            → bool
    list_proxies(profile_id)                  → list[dict]

    add_proxy(profile_id, url)                → bool
    remove_proxy(profile_id, url)             → bool

    get_proxy_health(profile_id)             → dict | None
    list_all_health()                         → list[dict]

    enable_proxy(profile_id, url)             → bool
    disable_proxy(profile_id, url)            → bool
    batch_enable(proxy_url)                   → int（启用了多少个 profile）
    batch_disable(proxy_url)                  → int（禁用了多少个 profile）

    mark_proxy_dead(profile_id, url)          → bool（失效剔除）
    reset_proxy_failures(profile_id, url)      → bool

导出 ProxyRotator 内部状态（用于调试/MCP 工具暴露）：
    get_rotator_status(profile_id)           → dict

T-097 新增（代理池策略可视化）：
    geoip_route(url)                         → dict | None（按 URL 地区选代理）
    get_pool_visual_status()                 → dict（池总览）
    set_health_check_interval(minutes)       → None（持久化到 pool.yaml）
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any, List

from Core.Profile.proxy_rotator import (
    ProxyRotator,
    ProxyPolicy,
    ProxyState,
    ProxyEntry,
)


# ─── 单例（惰性初始化）────────────────────────────────────────────────────────

_rotator: Optional[ProxyRotator] = None


def _get_rotator() -> ProxyRotator:
    global _rotator
    if _rotator is None:
        _rotator = ProxyRotator()
    return _rotator


# ─── 注册 / 注销 ─────────────────────────────────────────────────────────────

def register_proxies(profile_id: str, proxy_urls: List[str]) -> bool:
    """
    为 Profile 注册代理池（覆盖式）。

    Returns:
        True 成功
    """
    if not proxy_urls:
        return False
    rotator = _get_rotator()
    rotator.register(profile_id, proxy_urls)
    return True


def unregister_proxies(profile_id: str) -> bool:
    """
    注销 Profile 的所有代理状态。

    Returns:
        True 注销成功（之前有注册），False 原本就没有
    """
    rotator = _get_rotator()
    before = rotator.get_status(profile_id)
    rotator.unregister(profile_id)
    return before["proxies"] != []


def list_proxies(profile_id: str) -> List[dict]:
    """返回 Profile 当前注册的代理列表"""
    rotator = _get_rotator()
    status = rotator.get_status(profile_id)
    return status.get("proxies", [])


# ─── 单个代理增删 ─────────────────────────────────────────────────────────────

def add_proxy(profile_id: str, url: str) -> bool:
    """
    为 Profile 新增一个代理 URL（追加到现有池尾部）。

    Returns:
        True 新增成功，False 失败（已达上限 / URL 已存在）
    """
    rotator = _get_rotator()
    with rotator._lock:
        pool = rotator._proxy_pools.get(profile_id)
        if pool is None:
            rotator.register(profile_id, [url])
            return True
        if any(e.url == url for e in pool):
            return False  # 已存在
        if len(pool) >= rotator._policy.max_proxies_per_profile:
            return False  # 达上限
        pool.append(ProxyEntry(url=url))
        return True


def remove_proxy(profile_id: str, url: str) -> bool:
    """
    从 Profile 移除一个代理 URL。

    Returns:
        True 移了，False 本来就没有
    """
    rotator = _get_rotator()
    with rotator._lock:
        pool = rotator._proxy_pools.get(profile_id)
        if pool is None:
            return False
        for i, entry in enumerate(pool):
            if entry.url == url:
                pool.pop(i)
                return True
        return False


# ─── Health 报表 ─────────────────────────────────────────────────────────────

def get_proxy_health(profile_id: str) -> Optional[dict]:
    """
    返回 Profile 代理健康状态快照。

    Returns:
        None（profile 未注册），dict（健康状态）
    """
    rotator = _get_rotator()
    status = rotator.get_status(profile_id)
    proxies = status.get("proxies", [])
    if not proxies:
        return None
    return {
        "profile_id": profile_id,
        "total": len(proxies),
        "active": sum(1 for p in proxies if p["state"] == "active"),
        "cooldown": sum(1 for p in proxies if p["state"] == "cooldown"),
        "banned": sum(1 for p in proxies if p["state"] == "banned"),
        "current_index": status["current_index"],
        "consecutive_failures": status["profile_consecutive_failures"],
        "proxies": proxies,
    }


def list_all_health() -> List[dict]:
    """返回所有已注册 Profile 的健康状态列表（用于仪表盘）"""
    rotator = _get_rotator()
    with rotator._lock:
        profile_ids = list(rotator._proxy_pools.keys())

    results = []
    for pid in profile_ids:
        health = get_proxy_health(pid)
        if health:
            results.append(health)
    return results


# ─── 批量启用 / 禁用 ───────────────────────────────────────────────────────

def enable_proxy(profile_id: str, url: str) -> bool:
    """
    启用指定代理（解除 BANNED 状态，清除失败计数）。

    Returns:
        True 启了，False 原本就不是 BANNED 或 proxy 不存在
    """
    rotator = _get_rotator()
    with rotator._lock:
        pool = rotator._proxy_pools.get(profile_id)
        if pool is None:
            return False
        for entry in pool:
            if entry.url == url:
                if entry.state == ProxyState.BANNED:
                    entry.state = ProxyState.ACTIVE
                    entry.consecutive_failures = 0
                    entry.cooldown_until = None
                    return True
                return False
        return False


def disable_proxy(profile_id: str, url: str) -> bool:
    """
    禁用指定代理（设为 BANNED）。

    Returns:
        True 禁了，False proxy 不存在
    """
    rotator = _get_rotator()
    with rotator._lock:
        pool = rotator._proxy_pools.get(profile_id)
        if pool is None:
            return False
        for entry in pool:
            if entry.url == url:
                entry.state = ProxyState.BANNED
                return True
        return False


def batch_enable(proxy_url: str) -> int:
    """
    跨所有 Profile 启用指定 proxy URL。

    Returns:
        启用了多少个 profile 的该 proxy
    """
    rotator = _get_rotator()
    count = 0
    with rotator._lock:
        for pid, pool in rotator._proxy_pools.items():
            for entry in pool:
                if entry.url == proxy_url:
                    if entry.state == ProxyState.BANNED:
                        entry.state = ProxyState.ACTIVE
                        entry.consecutive_failures = 0
                        entry.cooldown_until = None
                        count += 1
    return count


def batch_disable(proxy_url: str) -> int:
    """
    跨所有 Profile 禁用指定 proxy URL。

    Returns:
        禁用了多少个 profile 的该 proxy
    """
    rotator = _get_rotator()
    count = 0
    with rotator._lock:
        for pid, pool in rotator._proxy_pools.items():
            for entry in pool:
                if entry.url == proxy_url:
                    entry.state = ProxyState.BANNED
                    count += 1
    return count


# ─── 失效剔除 ────────────────────────────────────────────────────────────────

def mark_proxy_dead(profile_id: str, url: str) -> bool:
    """
    失效剔除：将指定 proxy 立即标为 BANNED 并触发轮换到下一个。

    Returns:
        True 成功，False proxy 不存在
    """
    rotator = _get_rotator()
    with rotator._lock:
        pool = rotator._proxy_pools.get(profile_id)
        if pool is None:
            return False
        for i, entry in enumerate(pool):
            if entry.url == url:
                entry.state = ProxyState.BANNED
                entry.consecutive_failures = 0
                # 触发轮换到下一个
                n = len(pool)
                for offset in range(1, n):
                    next_idx = (i + offset) % n
                    if pool[next_idx].is_available():
                        rotator._current_index[profile_id] = next_idx
                        return True
                # 没有可用代理了
                return True  # BANNED 标记成功，只是没下一个可切
        return False


def reset_proxy_failures(profile_id: str, url: str) -> bool:
    """
    重置指定 proxy 的失败计数（不清除状态）。

    Returns:
        True 成功，False proxy 不存在
    """
    rotator = _get_rotator()
    with rotator._lock:
        pool = rotator._proxy_pools.get(profile_id)
        if pool is None:
            return False
        for entry in pool:
            if entry.url == url:
                entry.consecutive_failures = 0
                return True
        return False


# ─── T-097 代理池策略可视化 ───────────────────────────────────────────────

# URL TLD → 国家/地区映射（简单版，覆盖常见电商/社交）
_TLD_COUNTRY: dict[str, str] = {
    ".cn": "CN", ".com.cn": "CN", ".co.jp": "JP",
    ".co.uk": "GB", ".co.kr": "KR",
    ".de": "DE", ".fr": "FR", ".it": "IT", ".es": "ES",
    ".nl": "NL", ".se": "SE", ".pl": "PL",
    ".ru": "RU", ".ua": "UA",
    ".com.br": "BR", ".com.mx": "MX",
    ".in": "IN", ".th": "TH", ".vn": "VN", ".id": "ID", ".my": "MY",
    ".sg": "SG", ".au": "AU", ".nz": "NZ",
    ".ca": "CA",
    ".com": "US",  # 默认（美国/通用）
}

# 特定域名 → 国家映射（优先于 TLD 匹配）
_DOMAIN_COUNTRY: dict[str, str] = {
    "taobao.com": "CN",
    "tmall.com": "CN",
    "jd.com": "CN",
    "alibaba.com": "CN",
    "aliexpress.com": "CN",
    "amazon.co.jp": "JP",
    "rakuten.co.jp": "JP",
    "zozotown.com": "JP",
    "uniqlo.com": "JP",
    "coupang.com": "KR",
    "naver.com": "KR",
    " Tm": "KR",  # no
    "carousell.com": "SG",
    "qoo10.com": "SG",
}


def _url_to_country(url: str) -> str:
    """从 URL 提取目标国家代码（用于 geoip 路由）"""
    import re
    # 去掉协议
    host = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", url).split("/")[0].split("?")[0]
    host = host.split("@")[-1]  # 去掉 user:pass@
    # 先查域名级映射
    base = host.lower()
    for domain, country in _DOMAIN_COUNTRY.items():
        if base.endswith(domain):
            return country
    # 再按 TLD
    tld = "." + host.rsplit(".", 1)[-1].lower()
    return _TLD_COUNTRY.get(tld, "US")


def geoip_route(url: str, profile_id: str) -> Optional[dict]:
    """
    按 URL 目标地区自动选代理。

    1. 从 URL 解析 TLD → 国家代码
    2. 在 profile 的代理池里找对应 region 的 ACTIVE 代理
    3. 找不到 → 返回 None（走无代理或全局代理）

    Args:
        url: 目标 URL
        profile_id: Profile id

    Returns:
        {"url": str, "region": str, "scheme": str}  或 None
    """
    country = _url_to_country(url)
    rotator = _get_rotator()
    with rotator._lock:
        pool = rotator._proxy_pools.get(profile_id)
        if not pool:
            return None
        for entry in pool:
            if entry.state == ProxyState.ACTIVE and entry.region == country:
                return {
                    "url": entry.url,
                    "region": entry.region,
                    "country_matched": country,
                }
        # 找不到完全匹配，找任一 ACTIVE
        for entry in pool:
            if entry.state == ProxyState.ACTIVE:
                return {
                    "url": entry.url,
                    "region": entry.region,
                    "country_matched": country,
                    "fallback": True,
                }
        return None


def get_pool_visual_status() -> dict:
    """
    返回全局代理池可视化状态（供 7860 面板展示）。

    Returns:
        {
            "total": int,
            "by_state": {"active": int, "cooldown": int, "banned": int},
            "by_region": dict[str, int],  # region → count
            "profiles": list[dict],  # per-profile 汇总
        }
    """
    rotator = _get_rotator()
    with rotator._lock:
        total = 0
        by_state = {"active": 0, "cooldown": 0, "banned": 0}
        by_region: dict[str, int] = {}
        profiles_out: list[dict] = []

        for pid, pool in rotator._proxy_pools.items():
            p_active = p_cooldown = p_banned = 0
            p_regions: set[str] = set()
            for entry in pool:
                total += 1
                st = entry.state.value
                by_state[st] = by_state.get(st, 0) + 1
                if st == "active":
                    p_active += 1
                elif st == "cooldown":
                    p_cooldown += 1
                else:
                    p_banned += 1
                if entry.region:
                    by_region[entry.region] = by_region.get(entry.region, 0) + 1
                    p_regions.add(entry.region)
            profiles_out.append({
                "profile_id": pid,
                "total": len(pool),
                "active": p_active,
                "cooldown": p_cooldown,
                "banned": p_banned,
                "regions": sorted(p_regions),
            })

        return {
            "total": total,
            "by_state": by_state,
            "by_region": by_region,
            "profiles": profiles_out,
        }


def set_health_check_interval(minutes: int) -> None:
    """
    设置健康检测间隔，持久化到 ProfileStore 同级的 pool.yaml。

    Args:
        minutes: 检测间隔（分钟），<= 0 表示关闭自动检测
    """
    from Core.Profile.pool import _get_pool_instance
    pool = _get_pool_instance()
    if pool is not None:
        pool.set_health_check_interval(minutes)


# ─── 调试 / MCP 暴露 ─────────────────────────────────────────────────────────

def get_rotator_status(profile_id: str) -> dict:
    """返回 ProxyRotator 原始状态（调试用）"""
    return _get_rotator().get_status(profile_id)
