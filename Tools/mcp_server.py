"""
Tools/mcp_server.py — T-081 MCP Server 入口

用法:
    # stdio 模式（Claude Desktop）
    python Tools/mcp_server.py

    # HTTP 模式（mcpai）
    python Tools/mcp_server.py --transport http --port 7864

注册工具（24个）:
    Profile 组（8）: profile_list / profile_get / profile_create /
                     profile_update / profile_delete / profile_warmup /
                     profile_export / profile_import
    Proxy 组（8）:   proxy_list / proxy_get / proxy_create /
                     proxy_update / proxy_delete / proxy_health_check /
                     proxy_bulk_import / proxy_reset_health
    Pool 组（8）:    pool_acquire / pool_release / pool_status /
                     pool_ban / pool_cooldown / pool_set_strategy /
                     pool_set_max_concurrent / pool_uncooldown_profile
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── sys.path 设置（同目录运行时）────────────────────────────────────────────
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR.parent))

from mcp.server import FastMCP
from Core.Profile import ProfileStatus


# ── FastMCP instance（stdio 默认 port=8000，HTTP 模式在 main() 里重建）──

mcp = FastMCP(
    name="webauto",
    host="127.0.0.1",
    port=8000,
    instructions=(
        "WebAuto profile & proxy management MCP server. "
        "profile_* tools for profile CRUD. "
        "proxy_* tools for proxy CRUD and health. "
        "pool_* tools for runtime pool management."
    ),
)


# ════════════════════════════════════════════════════════════════════════════
# 工具实现函数
# ════════════════════════════════════════════════════════════════════════════

from Tools.profile_backend import (
    list_profiles, get_profile, create_profile, update_profile,
    delete_profile, warmup_profile, export_profile, import_profile,
    set_pool_strategy, set_pool_max_concurrent, get_pool_status,
    uncooldown_profile, _get_pool, _get_store,
)
from Tools.proxy_backend import (
    register_proxies, unregister_proxies, list_proxies,
    get_proxy_health, list_all_health, enable_proxy, disable_proxy,
    batch_enable, batch_disable, mark_proxy_dead, reset_proxy_failures,
    get_rotator_status,
)


def _profile_summary(p: Any) -> Dict[str, Any]:
    return {
        "id": p.id, "name": p.name,
        "status": p.status.value if hasattr(p.status, "value") else str(p.status),
        "tags": p.tags or [],
        "last_used": p.last_used.isoformat() if p.last_used else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _profile_detail(p: Any) -> Dict[str, Any]:
    fp = p.fingerprint
    net = p.network
    return {
        "id": p.id, "name": p.name,
        "status": p.status.value if hasattr(p.status, "value") else str(p.status),
        "tags": p.tags or [],
        "fingerprint": {
            "platform": fp.platform, "user_agent": fp.user_agent,
            "viewport": {"width": fp.viewport.width, "height": fp.viewport.height},
            "timezone": fp.timezone, "locale": fp.locale, "ua_mask_type": fp.ua_mask_type,
        },
        "network": {
            "proxy_url": net.proxy_url, "proxy_username": net.proxy_username,
            "proxy_password": "***", "proxy_type": net.proxy_type,
            "geoip_country": net.geoip_country, "dns_over_https": net.dns_over_https,
            "proxy_pool": net.proxy_pool or [],
        },
        "cooldown_until": p.cooldown_until.isoformat() if p.cooldown_until else None,
        "last_used": p.last_used.isoformat() if p.last_used else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "storage_dir": str(p.storage_dir) if p.storage_dir else None,
    }


# ════════════════════════════════════════════════════════════════════════════
# Profile 组（8 tools）
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool(name="profile_list", description="列出所有 Profile 摘要列表")
def profile_list() -> Dict[str, Any]:
    return {"profiles": [_profile_summary(p) for p in list_profiles()], "total": len(list_profiles())}


@mcp.tool(name="profile_get", description="获取单个 Profile 完整配置")
def profile_get(profile_id: str) -> Dict[str, Any]:
    p = get_profile(profile_id)
    if p is None:
        return {"error": "Profile not found", "profile_id": profile_id}
    return {"profile": _profile_detail(p)}


@mcp.tool(name="profile_create", description="创建新 Profile")
def profile_create(
    profile_id: str,
    name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    fingerprint: Optional[Dict[str, Any]] = None,
    network: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        p = create_profile({"id": profile_id, "name": name, "tags": tags,
                            "fingerprint": fingerprint, "network": network})
        return {"profile_id": p.id, "created": True,
                "storage_dir": str(p.storage_dir) if p.storage_dir else ""}
    except Exception as e:
        return {"error": str(e), "profile_id": profile_id}


@mcp.tool(name="profile_update", description="更新 Profile 配置（原子写）")
def profile_update(
    profile_id: str,
    name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    fingerprint: Optional[Dict[str, Any]] = None,
    network: Optional[Dict[str, Any]] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    data = {k: v for k, v in {
        "name": name, "tags": tags, "fingerprint": fingerprint,
        "network": network, "status": status,
    }.items() if v is not None}
    updated = update_profile(profile_id, data)
    if updated is None:
        return {"error": "Profile not found", "profile_id": profile_id}
    return {"profile_id": profile_id, "updated": True}


@mcp.tool(name="profile_delete", description="删除 Profile（可选擦除 storage）")
def profile_delete(profile_id: str, wipe_storage: bool = True) -> Dict[str, Any]:
    deleted = delete_profile(profile_id, wipe_storage=wipe_storage)
    return {"profile_id": profile_id, "deleted": deleted, "wiped": wipe_storage}


@mcp.tool(name="profile_warmup", description="预热 Profile（创建 user-data 目录）")
def profile_warmup(profile_id: str) -> Dict[str, Any]:
    p = warmup_profile(profile_id)
    if p is None:
        return {"error": "Profile not found", "profile_id": profile_id}
    return {"profile_id": profile_id, "warmed_up": True,
            "user_data_dir": str(p.storage_dir / "chromium") if p.storage_dir else ""}


@mcp.tool(name="profile_export", description="导出 Profile 为 .zip 包")
def profile_export(profile_id: str, target_path: str) -> Dict[str, Any]:
    result = export_profile(profile_id, target_path)
    if result is None:
        return {"error": "Profile not found", "profile_id": profile_id}
    return {"profile_id": profile_id, "exported": True,
            "path": result.get("path", target_path),
            "size_bytes": result.get("size_bytes", 0)}


@mcp.tool(name="profile_import", description="从 .zip 包导入 Profile")
def profile_import(source_path: str, new_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        p = import_profile({"source_path": source_path, "new_id": new_id})
        return {"profile_id": p.id, "imported": True,
                "storage_dir": str(p.storage_dir) if p.storage_dir else ""}
    except Exception as e:
        return {"error": str(e)}


# ════════════════════════════════════════════════════════════════════════════
# Proxy 组（8 tools）
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool(name="proxy_list", description="列出所有代理条目（不含健康详情）")
def proxy_list() -> Dict[str, Any]:
    proxies = list_proxies()
    return {
        "proxies": [
            {
                "id": px["id"], "url": px["url"],
                "proxy_type": px.get("proxy_type", "http"),
                "region": px.get("region"), "tags": px.get("tags", []),
                "enabled": px.get("enabled", True), "notes": px.get("notes", ""),
            }
            for px in proxies
        ],
        "total": len(proxies),
    }


@mcp.tool(name="proxy_get", description="获取单个代理详情（含健康状态）")
def proxy_get(proxy_id: str) -> Dict[str, Any]:
    health = get_proxy_health(proxy_id)
    if health is None:
        return {"error": "Proxy not found", "proxy_id": proxy_id}
    return {"proxy": health.get("proxy", {}), "health": health.get("health", {})}


@mcp.tool(name="proxy_create", description="添加新代理到全局池")
def proxy_create(
    url: str,
    proxy_id: Optional[str] = None,
    proxy_type: str = "http",
    username: Optional[str] = None,
    password: Optional[str] = None,
    region: Optional[str] = None,
    tags: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    result = register_proxies([{
        "id": proxy_id, "url": url, "proxy_type": proxy_type,
        "username": username, "password": password,
        "region": region, "tags": tags, "notes": notes,
    }])
    created = result.get(url, [None])[0]
    if created is None:
        return {"error": "Failed to register proxy", "url": url}
    return {"proxy_id": created, "created": True}


# proxy_update — 代理不支持原地修改，提示用 proxy_create
@mcp.tool(name="proxy_update", description="更新已有代理配置（暂不支持，建议用 proxy_create 新建）")
def proxy_update(proxy_id: str, **kwargs: Any) -> Dict[str, Any]:
    return {
        "error": "proxy_update not yet implemented. "
                 "Use proxy_create to add a proxy with a different id.",
        "proxy_id": proxy_id,
    }


@mcp.tool(name="proxy_delete", description="从全局池删除代理")
def proxy_delete(proxy_id: str) -> Dict[str, Any]:
    removed = unregister_proxies([proxy_id])
    return {"proxy_id": proxy_id, "deleted": proxy_id in removed}


@mcp.tool(name="proxy_health_check", description="对代理发起健康检查")
def proxy_health_check(
    proxy_id: str,
    test_url: str = "https://www.google.com",
    timeout: int = 10,
) -> Dict[str, Any]:
    health = get_proxy_health(proxy_id)
    if health is None:
        return {"error": "Proxy not found", "proxy_id": proxy_id}
    h = health.get("health", {})
    return {
        "proxy_id": proxy_id,
        "reachable": h.get("is_available", False),
        "state": h.get("state", "unknown"),
        "last_check": h.get("last_check"),
        "latency_ms": h.get("latency_ms_last"),
        "error": h.get("last_error"),
    }


@mcp.tool(name="proxy_bulk_import", description="从文件批量导入代理")
def proxy_bulk_import(
    source_path: str,
    format: str = "txt",
    default_tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    try:
        with open(source_path) as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except FileNotFoundError:
        return {"error": "File not found", "source_path": source_path}
    if format == "csv":
        import csv
        rows = []
        reader = csv.DictReader(lines)
        for row in reader:
            rows.append({
                "url": row.get("url"),
                "proxy_type": row.get("proxy_type", "http"),
                "username": row.get("username"),
                "password": row.get("password"),
                "region": row.get("region"),
                "tags": row.get("tags", "").split(",") if row.get("tags") else None,
            })
    else:
        rows = [{"url": ln} for ln in lines]
    result = register_proxies(rows)
    all_ids: List[str] = []
    for ids in result.values():
        all_ids.extend(ids)
    return {"imported": len(all_ids), "skipped": len(lines) - len(all_ids),
            "total": len(lines), "proxy_ids": all_ids}


@mcp.tool(name="proxy_reset_health", description="重置代理健康状态")
def proxy_reset_health(proxy_id: str, state: str = "active") -> Dict[str, Any]:
    prev = get_proxy_health(proxy_id)
    if prev is None:
        return {"error": "Proxy not found", "proxy_id": proxy_id}
    previous_state = prev.get("health", {}).get("state", "unknown")
    reset_proxy_failures(proxy_id)
    return {"proxy_id": proxy_id, "reset": True,
            "previous_state": previous_state, "new_state": state}


# ════════════════════════════════════════════════════════════════════════════
# Pool 组（8 tools）
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool(name="pool_acquire", description="从池中借出一个可用 Profile")
async def pool_acquire(tag: Optional[str] = None, timeout: float = 30.0) -> Dict[str, Any]:
    pool = _get_pool()
    try:
        profile = await asyncio.wait_for(pool.acquire(tag=tag), timeout=timeout)
        status = pool.get_status()
        return {
            "profile_id": profile.id, "acquired": True,
            "strategy": status.get("strategy", "unknown"),
            "in_use_count": status.get("running", 0),
        }
    except asyncio.TimeoutError:
        return {"error": f"No available profile for tag={tag} after {timeout}s",
                "acquired": False}


@mcp.tool(name="pool_release", description="归还 Profile 到池中")
async def pool_release(profile_id: str, cooldown: float = 0) -> Dict[str, Any]:
    pool = _get_pool()
    p = get_profile(profile_id)
    if p is None:
        return {"error": "Profile not found", "profile_id": profile_id}
    await pool.release(p, cooldown=cooldown)
    return {"profile_id": profile_id, "released": True,
            "cooldown_seconds": cooldown,
            "new_status": "cooldown" if cooldown > 0 else "ready"}


@mcp.tool(name="pool_status", description="获取池运行时状态快照")
def pool_status() -> Dict[str, Any]:
    return get_pool_status()


@mcp.tool(name="pool_ban", description="永久标记 Profile 为 banned")
def pool_ban(profile_id: str) -> Dict[str, Any]:
    p = get_profile(profile_id)
    if p is None:
        return {"error": "Profile not found", "profile_id": profile_id}
    prev = p.status.value if hasattr(p.status, "value") else str(p.status)
    p.status = ProfileStatus.BANNED
    _get_store().save(p)
    return {"profile_id": profile_id, "banned": True, "previous_status": prev}


@mcp.tool(name="pool_cooldown", description="将 Profile 设为临时 cooldown")
def pool_cooldown(profile_id: str, duration: float) -> Dict[str, Any]:
    from datetime import datetime, timedelta
    p = get_profile(profile_id)
    if p is None:
        return {"error": "Profile not found", "profile_id": profile_id}
    p.cooldown_until = datetime.now() + timedelta(seconds=duration)
    p.status = ProfileStatus.COOLDOWN
    _get_store().save(p)
    return {"profile_id": profile_id,
            "cooldown_until": p.cooldown_until.isoformat(),
            "new_status": "cooldown"}


@mcp.tool(name="pool_set_strategy", description="切换池的 Profile 选择策略")
def pool_set_strategy(strategy: str) -> Dict[str, Any]:
    pool = _get_pool()
    prev = pool.strategy.value if hasattr(pool.strategy, "value") else str(pool.strategy)
    set_pool_strategy(strategy)
    return {"previous_strategy": prev, "new_strategy": strategy, "persisted": True}


@mcp.tool(name="pool_set_max_concurrent", description="修改池的最大并发 Profile 数量")
def pool_set_max_concurrent(max_concurrent: int) -> Dict[str, Any]:
    pool = _get_pool()
    prev = pool.get_status().get("max_concurrent", 0)
    set_pool_max_concurrent(max_concurrent)
    status = pool.get_status()
    return {"previous_max": prev, "new_max": max_concurrent,
            "current_in_use": status.get("running", 0), "persisted": True}


@mcp.tool(name="pool_uncooldown_profile", description="提前解除 Profile 的 cooldown")
def pool_uncooldown_profile(profile_id: str) -> Dict[str, Any]:
    p = get_profile(profile_id)
    if p is None:
        return {"error": "Profile not found", "profile_id": profile_id}
    if not uncooldown_profile(profile_id):
        return {"error": "Profile is not in cooldown", "profile_id": profile_id}
    return {"profile_id": profile_id, "uncooled": True,
            "previous_status": "cooldown", "new_status": "ready"}


# ════════════════════════════════════════════════════════════════════════════
# main — 双传输模式
# ════════════════════════════════════════════════════════════════════════════

def _copy_mcp(host: str, port: int) -> FastMCP:
    """复制当前 mcp 的 tool 注册到新 FastMCP（不同 host/port）。"""
    instructions_str = (
        "WebAuto profile & proxy management MCP server. "
        "profile_* tools for profile CRUD. "
        "proxy_* tools for proxy CRUD and health. "
        "pool_* tools for runtime pool management."
    )
    new_mcp = FastMCP(name="webauto", host=host, port=port, instructions=instructions_str)
    for tool in mcp._tool_manager._tools.values():
        new_mcp.add_tool(tool.fn, name=tool.name, description=tool.description)
    return new_mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="WebAuto MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio（Claude Desktop）或 http（mcpai）",
    )
    parser.add_argument("--port", type=int, default=7864, help="HTTP 端口（默认 7864）")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP 监听地址（默认 0.0.0.0）")
    args = parser.parse_args()

    if args.transport == "http":
        server = _copy_mcp(host=args.host, port=args.port)
        server.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
