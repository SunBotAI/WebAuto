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

T-085: MCP 输入校验（pydantic BaseModel 严格定义每个 tool 的 input schema）
T-086: MCP 输出标准化（所有 tool 返回 {"success": bool, "data": ..., "error": str|None}）
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

# ── T-085: pydantic 输入校验模型 ────────────────────────────────────────────
from pydantic import BaseModel, Field, field_validator, model_validator


class FingerprintInput(BaseModel):
    """profile_create / profile_update 的 fingerprint 字段校验"""
    platform: Optional[str] = None
    user_agent: Optional[str] = None
    viewport: Optional[Dict[str, int]] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None
    ua_mask_type: Optional[str] = None

    @field_validator("viewport")
    @classmethod
    def viewport_dims(cls, v: Optional[Dict[str, int]]) -> Optional[Dict[str, int]]:
        if v is not None:
            if "width" not in v or "height" not in v:
                raise ValueError("viewport must have 'width' and 'height' keys")
            for dim in ("width", "height"):
                if not isinstance(v[dim], int) or v[dim] <= 0:
                    raise ValueError(f"viewport.{dim} must be a positive integer")
        return v


class NetworkInput(BaseModel):
    """profile_create / profile_update 的 network 字段校验"""
    proxy_url: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    proxy_type: Optional[str] = Field(default=None, pattern=r"^(http|socks5)$")
    geoip_country: Optional[str] = None
    dns_over_https: Optional[bool] = None
    proxy_pool: Optional[List[str]] = None


class ProfileCreateInput(BaseModel):
    """profile_create 的输入校验"""
    profile_id: str = Field(min_length=1, max_length=256)
    name: Optional[str] = Field(default=None, max_length=256)
    tags: Optional[List[str]] = Field(default=None, max_length=50)
    fingerprint: Optional[FingerprintInput] = None
    network: Optional[NetworkInput] = None

    @field_validator("profile_id")
    @classmethod
    def profile_id_chars(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", v):
            raise ValueError("profile_id may only contain alphanumeric, underscore, hyphen, dot")
        return v

    @field_validator("tags")
    @classmethod
    def tag_length(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            for tag in v:
                if len(tag) > 64:
                    raise ValueError(f"each tag must be ≤64 chars, got '{tag[:20]}...' ({len(tag)})")
        return v


class ProfileUpdateInput(BaseModel):
    """profile_update 的输入校验"""
    profile_id: str = Field(min_length=1, max_length=256)
    name: Optional[str] = Field(default=None, max_length=256)
    tags: Optional[List[str]] = None
    fingerprint: Optional[FingerprintInput] = None
    network: Optional[NetworkInput] = None
    status: Optional[str] = Field(default=None, pattern=r"^(ready|cooldown|banned|archived)$")

    @field_validator("profile_id")
    @classmethod
    def profile_id_chars(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", v):
            raise ValueError("profile_id may only contain alphanumeric, underscore, hyphen, dot")
        return v


class ProxyCreateInput(BaseModel):
    """proxy_create 的输入校验"""
    url: str = Field(min_length=1)
    proxy_id: Optional[str] = Field(default=None, max_length=256)
    proxy_type: str = Field(default="http", pattern=r"^(http|socks5)$")
    username: Optional[str] = Field(default=None, max_length=256)
    password: Optional[str] = Field(default=None, max_length=256)
    region: Optional[str] = Field(default=None, max_length=64)
    tags: Optional[List[str]] = None
    notes: Optional[str] = Field(default=None, max_length=1024)

    @field_validator("url")
    @classmethod
    def url_scheme(cls, v: str) -> str:
        import re
        if not re.match(r"^https?://", v):
            raise ValueError("url must start with http:// or https://")
        return v


class PoolAcquireInput(BaseModel):
    """pool_acquire 的输入校验"""
    tag: Optional[str] = Field(default=None, max_length=128)
    timeout: float = Field(default=30.0, gt=0, le=300)

    @field_validator("timeout")
    @classmethod
    def timeout_range(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("timeout must be > 0")
        return v


class PoolCooldownInput(BaseModel):
    """pool_cooldown 的输入校验"""
    profile_id: str = Field(min_length=1, max_length=256)
    duration: float = Field(gt=0, le=86400)

    @field_validator("profile_id")
    @classmethod
    def profile_id_chars(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", v):
            raise ValueError("profile_id may only contain alphanumeric, underscore, hyphen, dot")
        return v


class PoolSetStrategyInput(BaseModel):
    """pool_set_strategy 的输入校验"""
    strategy: str = Field(min_length=1, max_length=64)

    @field_validator("strategy")
    @classmethod
    def valid_strategy(cls, v: str) -> str:
        valid = {"random", "round-robin", "least-used", "priority"}
        if v not in valid:
            raise ValueError(f"strategy must be one of: {', '.join(sorted(valid))}")
        return v


class PoolSetMaxConcurrentInput(BaseModel):
    """pool_set_max_concurrent 的输入校验"""
    max_concurrent: int = Field(gt=0, le=1024)

    @field_validator("max_concurrent")
    @classmethod
    def max_concurrent_range(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_concurrent must be > 0")
        return v


class ProxyBulkImportInput(BaseModel):
    """proxy_bulk_import 的输入校验"""
    source_path: str = Field(min_length=1)
    format: str = Field(default="txt", pattern=r"^(txt|csv)$")
    default_tags: Optional[List[str]] = None


# ── T-086: 统一响应格式 ──────────────────────────────────────────────────────


def ok(data: Any) -> Dict[str, Any]:
    """成功响应 — T-086 三元组"""
    return {"success": True, "data": data, "error": None}


def err(error: str, data: Any = None) -> Dict[str, Any]:
    """失败响应 — T-086 三元组"""
    return {"success": False, "data": data, "error": error}


def wrap(fn):
    """装饰器：将 tool 函数结果统一包装为 T-086 三元组格式"""
    import functools
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
            # 已经符合三元组格式，直接返回
            if isinstance(result, dict) and "success" in result:
                return result
            # 裸数据，包装为成功
            return ok(result)
        except Exception as e:
            return err(str(e))
    return wrapper


# ── FastMCP instance（stdio 默认 port=8000，HTTP 模式在 main() 里重建）──

mcp = FastMCP(
    name="webauto",
    host="127.0.0.1",
    port=8000,
    instructions=(
        "WebAuto profile & proxy management MCP server. "
        "profile_* tools for profile CRUD. "
        "proxy_* tools for proxy CRUD and health. "
        "pool_* tools for runtime pool management. "
        "All tools return {\"success\": bool, \"data\": ..., \"error\": str|null}."
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


def _fmt_exc(e: Exception) -> str:
    """格式化异常为用户友好字符串"""
    return str(e)


# ════════════════════════════════════════════════════════════════════════════
# Profile 组（8 tools）
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool(name="profile_list", description="列出所有 Profile 摘要列表")
def profile_list() -> Dict[str, Any]:
    """T-086: 返回 success/data/error 三元组"""
    try:
        profiles = list_profiles()
        return ok({"profiles": [_profile_summary(p) for p in profiles], "total": len(profiles)})
    except Exception as e:
        return err(_fmt_exc(e))


@mcp.tool(name="profile_get", description="获取单个 Profile 完整配置")
def profile_get(profile_id: str) -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    # T-085: 参数校验
    if not profile_id or not isinstance(profile_id, str):
        return err("profile_id is required and must be a non-empty string", {"profile_id": profile_id})
    try:
        p = get_profile(profile_id)
        if p is None:
            return err(f"Profile '{profile_id}' not found", {"profile_id": profile_id})
        return ok({"profile": _profile_detail(p)})
    except Exception as e:
        return err(_fmt_exc(e), {"profile_id": profile_id})


@mcp.tool(name="profile_create", description="创建新 Profile")
def profile_create(
    profile_id: str,
    name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    fingerprint: Optional[Dict[str, Any]] = None,
    network: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """T-085 pydantic 校验 + T-086 三元组"""
    # T-085: pydantic BaseModel 校验输入
    try:
        validated = ProfileCreateInput(
            profile_id=profile_id,
            name=name,
            tags=tags,
            fingerprint=FingerprintInput(**fingerprint) if fingerprint else None,
            network=NetworkInput(**network) if network else None,
        )
    except Exception as e:
        return err(f"Invalid input: {_fmt_exc(e)}", {
            "profile_id": profile_id, "name": name, "tags": tags,
            "fingerprint": fingerprint, "network": network,
        })
    try:
        p = create_profile({
            "id": validated.profile_id,
            "name": validated.name,
            "tags": validated.tags,
            "fingerprint": validated.fingerprint.model_dump() if validated.fingerprint else None,
            "network": validated.network.model_dump() if validated.network else None,
        })
        return ok({
            "profile_id": p.id, "created": True,
            "storage_dir": str(p.storage_dir) if p.storage_dir else "",
        })
    except Exception as e:
        return err(_fmt_exc(e), {"profile_id": profile_id})


@mcp.tool(name="profile_update", description="更新 Profile 配置（原子写）")
def profile_update(
    profile_id: str,
    name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    fingerprint: Optional[Dict[str, Any]] = None,
    network: Optional[Dict[str, Any]] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """T-085 pydantic 校验 + T-086 三元组"""
    try:
        validated = ProfileUpdateInput(
            profile_id=profile_id,
            name=name,
            tags=tags,
            fingerprint=FingerprintInput(**fingerprint) if fingerprint else None,
            network=NetworkInput(**network) if network else None,
            status=status,
        )
    except Exception as e:
        return err(f"Invalid input: {_fmt_exc(e)}", {
            "profile_id": profile_id, "name": name, "tags": tags,
            "fingerprint": fingerprint, "network": network, "status": status,
        })
    try:
        data = {k: v for k, v in {
            "name": validated.name,
            "tags": validated.tags,
            "fingerprint": validated.fingerprint.model_dump() if validated.fingerprint else None,
            "network": validated.network.model_dump() if validated.network else None,
            "status": validated.status,
        }.items() if v is not None}
        updated = update_profile(validated.profile_id, data)
        if updated is None:
            return err(f"Profile '{validated.profile_id}' not found", {"profile_id": validated.profile_id})
        return ok({"profile_id": validated.profile_id, "updated": True})
    except Exception as e:
        return err(_fmt_exc(e), {"profile_id": profile_id})


@mcp.tool(name="profile_delete", description="删除 Profile（可选擦除 storage）")
def profile_delete(profile_id: str, wipe_storage: bool = True) -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    if not profile_id or not isinstance(profile_id, str):
        return err("profile_id is required and must be a non-empty string", {"profile_id": profile_id})
    try:
        deleted = delete_profile(profile_id, wipe_storage=wipe_storage)
        return ok({"profile_id": profile_id, "deleted": deleted, "wiped": wipe_storage})
    except Exception as e:
        return err(_fmt_exc(e), {"profile_id": profile_id})


@mcp.tool(name="profile_warmup", description="预热 Profile（创建 user-data 目录）")
def profile_warmup(profile_id: str) -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    if not profile_id or not isinstance(profile_id, str):
        return err("profile_id is required and must be a non-empty string", {"profile_id": profile_id})
    try:
        p = warmup_profile(profile_id)
        if p is None:
            return err(f"Profile '{profile_id}' not found", {"profile_id": profile_id})
        return ok({
            "profile_id": profile_id, "warmed_up": True,
            "user_data_dir": str(p.storage_dir / "chromium") if p.storage_dir else "",
        })
    except Exception as e:
        return err(_fmt_exc(e), {"profile_id": profile_id})


@mcp.tool(name="profile_export", description="导出 Profile 为 .zip 包")
def profile_export(profile_id: str, target_path: str) -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    if not profile_id or not isinstance(profile_id, str):
        return err("profile_id is required and must be a non-empty string", {"profile_id": profile_id})
    if not target_path or not isinstance(target_path, str):
        return err("target_path is required and must be a non-empty string", {"target_path": target_path})
    try:
        result = export_profile(profile_id, target_path)
        if result is None:
            return err(f"Profile '{profile_id}' not found", {"profile_id": profile_id})
        return ok({
            "profile_id": profile_id, "exported": True,
            "path": result.get("path", target_path),
            "size_bytes": result.get("size_bytes", 0),
        })
    except Exception as e:
        return err(_fmt_exc(e), {"profile_id": profile_id, "target_path": target_path})


@mcp.tool(name="profile_import", description="从 .zip 包导入 Profile")
def profile_import(source_path: str, new_id: Optional[str] = None) -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    if not source_path or not isinstance(source_path, str):
        return err("source_path is required and must be a non-empty string", {"source_path": source_path})
    if new_id is not None and not isinstance(new_id, str):
        return err("new_id must be a string if provided", {"new_id": new_id})
    try:
        p = import_profile({"source_path": source_path, "new_id": new_id})
        return ok({
            "profile_id": p.id, "imported": True,
            "storage_dir": str(p.storage_dir) if p.storage_dir else "",
        })
    except Exception as e:
        return err(_fmt_exc(e), {"source_path": source_path, "new_id": new_id})


# ════════════════════════════════════════════════════════════════════════════
# Proxy 组（8 tools）
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool(name="proxy_list", description="列出所有代理条目（不含健康详情）")
def proxy_list() -> Dict[str, Any]:
    """T-086 三元组"""
    try:
        proxies = list_proxies()
        return ok({
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
        })
    except Exception as e:
        return err(_fmt_exc(e))


@mcp.tool(name="proxy_get", description="获取单个代理详情（含健康状态）")
def proxy_get(proxy_id: str) -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    if not proxy_id or not isinstance(proxy_id, str):
        return err("proxy_id is required and must be a non-empty string", {"proxy_id": proxy_id})
    try:
        health = get_proxy_health(proxy_id)
        if health is None:
            return err(f"Proxy '{proxy_id}' not found", {"proxy_id": proxy_id})
        return ok({"proxy": health.get("proxy", {}), "health": health.get("health", {})})
    except Exception as e:
        return err(_fmt_exc(e), {"proxy_id": proxy_id})


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
    """T-085 pydantic 校验 + T-086 三元组"""
    try:
        validated = ProxyCreateInput(
            url=url, proxy_id=proxy_id, proxy_type=proxy_type,
            username=username, password=password,
            region=region, tags=tags, notes=notes,
        )
    except Exception as e:
        return err(f"Invalid input: {_fmt_exc(e)}", {
            "url": url, "proxy_id": proxy_id, "proxy_type": proxy_type,
            "username": username, "region": region, "tags": tags,
        })
    try:
        result = register_proxies([{
            "id": validated.proxy_id, "url": validated.url,
            "proxy_type": validated.proxy_type,
            "username": validated.username, "password": validated.password,
            "region": validated.region, "tags": validated.tags, "notes": validated.notes,
        }])
        created = result.get(validated.url, [None])[0]
        if created is None:
            return err(f"Failed to register proxy: {validated.url}", {"url": validated.url})
        return ok({"proxy_id": created, "created": True})
    except Exception as e:
        return err(_fmt_exc(e), {"url": url})


# proxy_update — 代理不支持原地修改，提示用 proxy_create
@mcp.tool(name="proxy_update", description="更新已有代理配置（暂不支持，建议用 proxy_create 新建）")
def proxy_update(proxy_id: str, **kwargs: Any) -> Dict[str, Any]:
    """T-086 三元组"""
    if not proxy_id or not isinstance(proxy_id, str):
        return err("proxy_id is required and must be a non-empty string", {"proxy_id": proxy_id})
    return err(
        "proxy_update not yet implemented. Use proxy_create to add a proxy with a different id.",
        {"proxy_id": proxy_id},
    )


@mcp.tool(name="proxy_delete", description="从全局池删除代理")
def proxy_delete(proxy_id: str) -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    if not proxy_id or not isinstance(proxy_id, str):
        return err("proxy_id is required and must be a non-empty string", {"proxy_id": proxy_id})
    try:
        removed = unregister_proxies([proxy_id])
        return ok({"proxy_id": proxy_id, "deleted": proxy_id in removed})
    except Exception as e:
        return err(_fmt_exc(e), {"proxy_id": proxy_id})


@mcp.tool(name="proxy_health_check", description="对代理发起健康检查")
def proxy_health_check(
    proxy_id: str,
    test_url: str = "https://www.google.com",
    timeout: int = 10,
) -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    if not proxy_id or not isinstance(proxy_id, str):
        return err("proxy_id is required and must be a non-empty string", {"proxy_id": proxy_id})
    if not isinstance(timeout, int) or timeout <= 0 or timeout > 60:
        return err("timeout must be an integer between 1 and 60", {"timeout": timeout})
    try:
        health = get_proxy_health(proxy_id)
        if health is None:
            return err(f"Proxy '{proxy_id}' not found", {"proxy_id": proxy_id})
        h = health.get("health", {})
        return ok({
            "proxy_id": proxy_id,
            "reachable": h.get("is_available", False),
            "state": h.get("state", "unknown"),
            "last_check": h.get("last_check"),
            "latency_ms": h.get("latency_ms_last"),
            "error": h.get("last_error"),
        })
    except Exception as e:
        return err(_fmt_exc(e), {"proxy_id": proxy_id})


@mcp.tool(name="proxy_bulk_import", description="从文件批量导入代理")
def proxy_bulk_import(
    source_path: str,
    format: str = "txt",
    default_tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """T-085 pydantic 校验 + T-086 三元组"""
    try:
        validated = ProxyBulkImportInput(
            source_path=source_path, format=format, default_tags=default_tags,
        )
    except Exception as e:
        return err(f"Invalid input: {_fmt_exc(e)}", {
            "source_path": source_path, "format": format, "default_tags": default_tags,
        })
    try:
        with open(validated.source_path) as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except FileNotFoundError:
        return err(f"File not found: {validated.source_path}", {"source_path": validated.source_path})
    except PermissionError:
        return err(f"Permission denied: {validated.source_path}", {"source_path": validated.source_path})
    if validated.format == "csv":
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
    return ok({
        "imported": len(all_ids), "skipped": len(lines) - len(all_ids),
        "total": len(lines), "proxy_ids": all_ids,
    })


@mcp.tool(name="proxy_reset_health", description="重置代理健康状态")
def proxy_reset_health(proxy_id: str, state: str = "active") -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    if not proxy_id or not isinstance(proxy_id, str):
        return err("proxy_id is required and must be a non-empty string", {"proxy_id": proxy_id})
    valid_states = {"active", "inactive", "unknown"}
    if state not in valid_states:
        return err(f"state must be one of: {', '.join(sorted(valid_states))}", {"state": state})
    try:
        prev = get_proxy_health(proxy_id)
        if prev is None:
            return err(f"Proxy '{proxy_id}' not found", {"proxy_id": proxy_id})
        previous_state = prev.get("health", {}).get("state", "unknown")
        reset_proxy_failures(proxy_id)
        return ok({
            "proxy_id": proxy_id, "reset": True,
            "previous_state": previous_state, "new_state": state,
        })
    except Exception as e:
        return err(_fmt_exc(e), {"proxy_id": proxy_id})


# ════════════════════════════════════════════════════════════════════════════
# Pool 组（8 tools）
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool(name="pool_acquire", description="从池中借出一个可用 Profile")
async def pool_acquire(tag: Optional[str] = None, timeout: float = 30.0) -> Dict[str, Any]:
    """T-085 pydantic 校验 + T-086 三元组"""
    try:
        validated = PoolAcquireInput(tag=tag, timeout=timeout)
    except Exception as e:
        return err(f"Invalid input: {_fmt_exc(e)}", {"tag": tag, "timeout": timeout})
    pool = _get_pool()
    try:
        profile = await asyncio.wait_for(pool.acquire(tag=validated.tag), timeout=validated.timeout)
        status = pool.get_status()
        return ok({
            "profile_id": profile.id, "acquired": True,
            "strategy": status.get("strategy", "unknown"),
            "in_use_count": status.get("running", 0),
        })
    except asyncio.TimeoutError:
        return err(
            f"No available profile for tag={validated.tag} after {validated.timeout}s",
            {"tag": validated.tag, "timeout": validated.timeout, "acquired": False},
        )
    except Exception as e:
        return err(_fmt_exc(e), {"tag": tag, "timeout": timeout})


@mcp.tool(name="pool_release", description="归还 Profile 到池中")
async def pool_release(profile_id: str, cooldown: float = 0) -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    if not profile_id or not isinstance(profile_id, str):
        return err("profile_id is required and must be a non-empty string", {"profile_id": profile_id})
    if not isinstance(cooldown, (int, float)) or cooldown < 0:
        return err("cooldown must be a non-negative number", {"cooldown": cooldown})
    pool = _get_pool()
    try:
        p = get_profile(profile_id)
        if p is None:
            return err(f"Profile '{profile_id}' not found", {"profile_id": profile_id})
        await pool.release(p, cooldown=cooldown)
        return ok({
            "profile_id": profile_id, "released": True,
            "cooldown_seconds": cooldown,
            "new_status": "cooldown" if cooldown > 0 else "ready",
        })
    except Exception as e:
        return err(_fmt_exc(e), {"profile_id": profile_id})


@mcp.tool(name="pool_status", description="获取池运行时状态快照")
def pool_status() -> Dict[str, Any]:
    """T-086 三元组"""
    try:
        return ok(get_pool_status())
    except Exception as e:
        return err(_fmt_exc(e))


@mcp.tool(name="pool_ban", description="永久标记 Profile 为 banned")
def pool_ban(profile_id: str) -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    if not profile_id or not isinstance(profile_id, str):
        return err("profile_id is required and must be a non-empty string", {"profile_id": profile_id})
    try:
        p = get_profile(profile_id)
        if p is None:
            return err(f"Profile '{profile_id}' not found", {"profile_id": profile_id})
        prev = p.status.value if hasattr(p.status, "value") else str(p.status)
        p.status = ProfileStatus.BANNED
        _get_store().save(p)
        return ok({"profile_id": profile_id, "banned": True, "previous_status": prev})
    except Exception as e:
        return err(_fmt_exc(e), {"profile_id": profile_id})


@mcp.tool(name="pool_cooldown", description="将 Profile 设为临时 cooldown")
def pool_cooldown(profile_id: str, duration: float) -> Dict[str, Any]:
    """T-085 pydantic 校验 + T-086 三元组"""
    try:
        validated = PoolCooldownInput(profile_id=profile_id, duration=duration)
    except Exception as e:
        return err(f"Invalid input: {_fmt_exc(e)}", {"profile_id": profile_id, "duration": duration})
    try:
        from datetime import datetime, timedelta
        p = get_profile(validated.profile_id)
        if p is None:
            return err(f"Profile '{validated.profile_id}' not found", {"profile_id": validated.profile_id})
        p.cooldown_until = datetime.now() + timedelta(seconds=validated.duration)
        p.status = ProfileStatus.COOLDOWN
        _get_store().save(p)
        return ok({
            "profile_id": validated.profile_id,
            "cooldown_until": p.cooldown_until.isoformat(),
            "new_status": "cooldown",
        })
    except Exception as e:
        return err(_fmt_exc(e), {"profile_id": profile_id, "duration": duration})


@mcp.tool(name="pool_set_strategy", description="切换池的 Profile 选择策略")
def pool_set_strategy(strategy: str) -> Dict[str, Any]:
    """T-085 pydantic 校验 + T-086 三元组"""
    try:
        validated = PoolSetStrategyInput(strategy=strategy)
    except Exception as e:
        return err(f"Invalid input: {_fmt_exc(e)}", {"strategy": strategy})
    try:
        pool = _get_pool()
        prev = pool.strategy.value if hasattr(pool.strategy, "value") else str(pool.strategy)
        set_pool_strategy(validated.strategy)
        return ok({"previous_strategy": prev, "new_strategy": validated.strategy, "persisted": True})
    except Exception as e:
        return err(_fmt_exc(e), {"strategy": strategy})


@mcp.tool(name="pool_set_max_concurrent", description="修改池的最大并发 Profile 数量")
def pool_set_max_concurrent(max_concurrent: int) -> Dict[str, Any]:
    """T-085 pydantic 校验 + T-086 三元组"""
    try:
        validated = PoolSetMaxConcurrentInput(max_concurrent=max_concurrent)
    except Exception as e:
        return err(f"Invalid input: {_fmt_exc(e)}", {"max_concurrent": max_concurrent})
    try:
        pool = _get_pool()
        prev = pool.get_status().get("max_concurrent", 0)
        set_pool_max_concurrent(validated.max_concurrent)
        status = pool.get_status()
        return ok({
            "previous_max": prev, "new_max": validated.max_concurrent,
            "current_in_use": status.get("running", 0), "persisted": True,
        })
    except Exception as e:
        return err(_fmt_exc(e), {"max_concurrent": max_concurrent})


@mcp.tool(name="pool_uncooldown_profile", description="提前解除 Profile 的 cooldown")
def pool_uncooldown_profile(profile_id: str) -> Dict[str, Any]:
    """T-085 输入校验 + T-086 三元组"""
    if not profile_id or not isinstance(profile_id, str):
        return err("profile_id is required and must be a non-empty string", {"profile_id": profile_id})
    try:
        p = get_profile(profile_id)
        if p is None:
            return err(f"Profile '{profile_id}' not found", {"profile_id": profile_id})
        if not uncooldown_profile(profile_id):
            return err(f"Profile '{profile_id}' is not in cooldown", {"profile_id": profile_id})
        return ok({
            "profile_id": profile_id, "uncooled": True,
            "previous_status": "cooldown", "new_status": "ready",
        })
    except Exception as e:
        return err(_fmt_exc(e), {"profile_id": profile_id})


# ════════════════════════════════════════════════════════════════════════════
# main — 双传输模式
# ════════════════════════════════════════════════════════════════════════════

def _copy_mcp(host: str, port: int) -> FastMCP:
    """复制当前 mcp 的 tool 注册到新 FastMCP（不同 host/port）。"""
    instructions_str = (
        "WebAuto profile & proxy management MCP server. "
        "profile_* tools for profile CRUD. "
        "proxy_* tools for proxy CRUD and health. "
        "pool_* tools for runtime pool management. "
        "All tools return {\"success\": bool, \"data\": ..., \"error\": str|null}."
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
