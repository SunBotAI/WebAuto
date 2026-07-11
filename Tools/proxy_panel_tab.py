"""Proxy Tab — Gradio Tab 实现，供 proxy_panel.py 和 webauto_web.py 共用。

不要直接 launch 此文件，用 proxy_panel.py 或 webauto_web.py 启动。
"""
from __future__ import annotations

import json as _json
import re
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Core.ProxyPool.health import ProxyHealthStore
    from Core.ProxyPool.proxy import Proxy

import gradio as gr

from Core.ProxyPool.health import (
    ProxyHealthRecord,
    ProxyHealthState,
    ProxyHealthStore,
)
from Core.ProxyPool.proxy import Proxy


# ─── 全局后端（与 proxy_panel.py 共享）────────────────────────────

_health_store: ProxyHealthStore | None = None


def _get_health_store() -> ProxyHealthStore:
    global _health_store
    if _health_store is None:
        _health_store = ProxyHealthStore()
    return _health_store


# ─── 内存态代理列表 ────────────────────────────────────────────────

_proxy_list: list[Proxy] = []


def _get_proxy_list() -> list[Proxy]:
    return _proxy_list


# ─── URL 解析 ────────────────────────────────────────────────────

_URL_RE = re.compile(
    r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*)://"
    r"((?P<user>[^:@]+):(?P<pass>[^@]+)@)?"
    r"(?P<host>[^/@]+)"
    r"(?P<path>/.*)?$"
)


def _parse_proxy_url(url: str) -> dict:
    m = _URL_RE.match(url.strip())
    if not m:
        return dict(url=url, scheme="http", host=url, user="", pass_="")
    scheme = m.group("scheme") or "http"
    host = m.group("host") or ""
    user = m.group("user") or ""
    pw = m.group("pass") or ""
    if ":" in host and not host.startswith("["):
        parts = host.rsplit(":", 1)
        host = parts[0]
    return dict(url=url, scheme=scheme, host=host, user=user, pass_=pw)


# ─── 格式化 helpers ──────────────────────────────────────────────

def _proxy_state_emoji(state: str) -> str:
    return {
        ProxyHealthState.ACTIVE.value: "🟢 ACTIVE",
        ProxyHealthState.COOLDOWN.value: "🟡 COOLDOWN",
        ProxyHealthState.BANNED.value: "🔴 BANNED",
    }.get(state, "⚪ UNKNOWN")


def _proxy_to_row(p: Proxy, health: ProxyHealthRecord) -> list[Any]:
    cooldown_str = ""
    if (
        health.state == ProxyHealthState.COOLDOWN.value
        and health.cooldown_until
    ):
        remaining = max(0, health.cooldown_until - time.time())
        cooldown_str = f"{remaining:.0f}s"
    lat_str = f"{health.latency_ms_avg:.0f}ms" if health.latency_ms_avg > 0 else "-"
    return [
        p.id,
        p.region or "",
        p.url[:40] + "..." if len(p.url) > 40 else p.url,
        ",".join(p.tags) if p.tags else "",
        "✅" if p.enabled else "❌",
        _proxy_state_emoji(health.state),
        str(health.consecutive_failures),
        str(health.failure_count),
        str(health.success_count),
        lat_str,
        cooldown_str,
    ]


def _all_rows() -> list[list[Any]]:
    health_store = _get_health_store()
    proxies = _get_proxy_list()
    health_map = health_store.load_all()
    rows = []
    for p in proxies:
        h = health_map.get(p.id, ProxyHealthRecord(proxy_id=p.id))
        rows.append(_proxy_to_row(p, h))
    return rows


# ─── Tab builder ─────────────────────────────────────────────────

def build_proxy_tab() -> None:
    """
    在当前 Gradio Blocks 上下文中追加 Proxy 管理 Tab。

    调用方式（在 Gradio with Block 内）:
        with gr.Tab("🌐 Proxy"):
            build_proxy_tab()
    """
    health_store = _get_health_store()
    proxies = _get_proxy_list()

    # ── Tab1: 代理列表 CRUD ──────────────────────────────────

    gr.Markdown("### 🌐 Proxy 管理")
    gr.Markdown("**🟢可用 🟡冷却 🔴封禁**")

    t1_refresh = gr.Button("🔄 刷新列表", variant="secondary")
    t1_table = gr.Dataframe(
        headers=[
            "ID", "Region", "URL(截断)", "标签", "启用",
            "健康状态", "连败", "总失败", "总成功", "平均延迟", "CD剩余",
        ],
        datatype=["str"] * 11,
        value=_all_rows(),
        interactive=False,
        max_height=300,
    )
    t1_refresh.click(fn=_all_rows, outputs=t1_table)

    gr.Markdown("---")
    gr.Markdown("### ➕ 添加 / ✏️ 编辑")

    with gr.Row():
        with gr.Column():
            a_url = gr.Textbox(
                label="代理 URL",
                placeholder="http://user:***@host:port",
            )
            a_region = gr.Textbox(
                label="Region（ISO，如 CN/US/JP）",
                placeholder="US",
            )
            a_tags = gr.Textbox(
                label="标签（逗号分隔）",
                placeholder="residential, datacenter",
            )
            a_notes = gr.Textbox(label="备注")
            a_btn = gr.Button("✅ 添加代理", variant="primary")
            a_result = gr.Textbox(label="操作结果", interactive=False, lines=4)

        with gr.Column():
            e_id = gr.Textbox(label="Proxy ID（编辑/删除）")
            e_url = gr.Textbox(label="新 URL（不改留空）")
            e_region = gr.Textbox(label="新 Region（不改留空）")
            e_enabled = gr.Checkbox(label="启用", value=True)
            with gr.Row():
                e_save = gr.Button("💾 保存", variant="primary")
                e_del = gr.Button("🗑️ 删除", variant="stop")
            e_result = gr.Textbox(label="操作结果", interactive=False, lines=3)

    gr.Markdown("---")
    gr.Markdown("### 📥 批量导入")

    with gr.Row():
        with gr.Column():
            t1_batch_file = gr.File(
                label="JSON 文件（array of proxy objects）",
                file_count="single",
                file_types=[".json"],
            )
            t1_batch_format = gr.Dropdown(
                label="导入格式",
                choices=["JSON（proxy 对象列表）", "纯文本（一行一个 URL）"],
                value="JSON（proxy 对象列表）",
            )
            t1_batch_btn = gr.Button("📥 批量导入", variant="primary")

        with gr.Column():
            t1_batch_result = gr.Textbox(
                label="导入结果",
                interactive=False,
                lines=5,
            )

    # ── Tab2: 健康面板 ────────────────────────────────────────

    gr.Markdown("---")
    gr.Markdown("### 🔧 健康面板")

    with gr.Row():
        t2_refresh = gr.Button("🔄 刷新", variant="secondary")
        t2_recover_all_btn = gr.Button(
            "🔁 一键恢复全部 COOLDOWN → ACTIVE",
            variant="secondary",
        )

    with gr.Row():
        t2_summary = gr.JSON(label="汇总统计", value={})

    gr.Markdown("### 详细健康记录")

    t2_table = gr.Dataframe(
        headers=[
            "ID", "State", "连败次数", "总失败", "总成功",
            "延迟均(ms)", "最后检查", "最后成功", "最后失败",
            "Cooldown Until", "最近错误",
        ],
        datatype=["str"] * 11,
        value=[],
        interactive=False,
        max_height=300,
    )

    gr.Markdown("### 单条操作")

    with gr.Row():
        with gr.Column():
            t2_pid = gr.Textbox(label="Proxy ID")
            h_cooldown_btn = gr.Button(
                "🔸 标记 COOLDOWN（300s）",
                variant="stop",
            )
            h_ban_btn = gr.Button("🔴 标记 BANNED", variant="stop")
            h_active_btn = gr.Button("🟢 标记 ACTIVE", variant="primary")
            h_reset_btn = gr.Button("🔄 重置健康记录", variant="secondary")
            h_result = gr.Textbox(
                label="操作结果",
                interactive=False,
                lines=3,
            )

    # ── Tab3: Playwright 用法 ────────────────────────────────

    gr.Markdown("---")
    gr.Markdown("### 🖥️ Playwright Proxy 用法")

    gr.Markdown("""
**Proxy 三元组格式**（用于 `browser.new_context(proxy=...)`）:

```python
proxy = {
    "server": "http://host:port",   # 无认证 URL
    "username": "user",             # 认证用户（无认证则省略）
    "password": "***",            # 认证密码（无认证则省略）
}
```

**从 Proxy 对象获取三元组：**

```python
from Core.ProxyPool.proxy import Proxy

p = Proxy(
    id="proxy-001",
    url="http://user:***@proxy.example.com:8080",
    region="US",
    tags=["residential"],
)

server, username, password = p.get_playwright_proxy()
# server   = "http://proxy.example.com:8080"
# username = "user"
# password = "pass"

context = await browser.new_context(
    proxy={"server": server, "username": username, "password": password}
)
```
""")

    with gr.Row():
        t3_refresh = gr.Button("🔄 刷新预览", variant="secondary")
        t3_table = gr.Dataframe(
            headers=["Proxy ID", "Region", "server", "username", "password", "已解析"],
            datatype=["str"] * 6,
            value=[],
            interactive=False,
        )

    # ═══════════════════════════════════════════════════════════════
    # 事件绑定
    # ═══════════════════════════════════════════════════════════════

    def _do_add(
        url: str, region: str, tags_str: str, notes: str,
    ) -> tuple[str, list]:
        if not url.strip():
            return "⚠️ URL 不能为空", _all_rows()
        parsed = _parse_proxy_url(url.strip())
        proxy = Proxy(
            id=f"proxy-{uuid.uuid4().hex[:8]}",
            url=url.strip(),
            region=region.strip().upper() if region.strip() else None,
            tags=[t.strip() for t in tags_str.split(",") if t.strip()],
            notes=notes.strip(),
            enabled=True,
        )
        if parsed.get("user"):
            proxy.username = parsed["user"]
        if parsed.get("pass"):
            proxy.password = parsed["pass"]
        proxies.append(proxy)
        health_store.upsert(ProxyHealthRecord(proxy_id=proxy.id))
        return (
            f"✅ 添加成功: {proxy.id}\n"
            f"URL: {proxy.url}\n"
            f"Region: {proxy.region or '-'}",
            _all_rows(),
        )

    def _do_save(
        pid: str, new_url: str, new_region: str, enabled: bool,
    ) -> str:
        if not pid.strip():
            return "⚠️ Proxy ID 不能为空"
        for p in proxies:
            if p.id == pid.strip():
                if new_url.strip():
                    parsed = _parse_proxy_url(new_url.strip())
                    p.url = new_url.strip()
                    if parsed.get("user"):
                        p.username = parsed["user"]
                    if parsed.get("pass"):
                        p.password = parsed["pass"]
                if new_region.strip():
                    p.region = new_region.strip().upper()
                p.enabled = enabled
                return f"✅ 已保存: {p.id}"
        return f"❌ 未找到 Proxy: {pid}"

    def _do_delete(pid: str) -> str:
        if not pid.strip():
            return "⚠️ Proxy ID 不能为空"
        for i, p in enumerate(proxies):
            if p.id == pid.strip():
                proxies.pop(i)
                health_store.delete(pid.strip())
                return f"✅ 已删除: {pid}"
        return f"❌ 未找到 Proxy: {pid}"

    def _do_batch_import(file_path: str, fmt: str) -> str:
        if not file_path:
            return "⚠️ 请先上传文件"
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = f.read().strip()

            if fmt.startswith("纯文本"):
                lines = [
                    ln.strip()
                    for ln in raw.splitlines()
                    if ln.strip() and not ln.startswith("#")
                ]
                count = 0
                for line in lines:
                    parsed = _parse_proxy_url(line)
                    proxy = Proxy(
                        id=f"proxy-{uuid.uuid4().hex[:8]}",
                        url=line,
                        region=None,
                        tags=[],
                        enabled=True,
                    )
                    if parsed.get("user"):
                        proxy.username = parsed["user"]
                    if parsed.get("pass"):
                        proxy.password = parsed["pass"]
                    proxies.append(proxy)
                    health_store.upsert(ProxyHealthRecord(proxy_id=proxy.id))
                    count += 1
                return f"✅ 导入 {count} 个代理（纯文本模式）"
            else:
                data = _json.loads(raw)
                items = data if isinstance(data, list) else [data]
                count = 0
                for item in items:
                    if isinstance(item, str):
                        item = {"url": item}
                    parsed = _parse_proxy_url(item.get("url", ""))
                    proxy = Proxy(
                        id=item.get("id") or f"proxy-{uuid.uuid4().hex[:8]}",
                        url=item.get("url", ""),
                        region=item.get("region"),
                        tags=item.get("tags", []),
                        notes=item.get("notes", ""),
                        enabled=item.get("enabled", True),
                    )
                    if parsed.get("user"):
                        proxy.username = parsed["user"]
                    if parsed.get("pass"):
                        proxy.password = parsed["pass"]
                    proxies.append(proxy)
                    health_store.upsert(ProxyHealthRecord(proxy_id=proxy.id))
                    count += 1
                return f"✅ 导入 {count} 个代理（JSON 模式）"
        except Exception as e:
            return f"❌ 导入失败: {e}"

    def _build_health_rows() -> tuple[dict, list[list]]:
        hmap = health_store.load_all()
        summary = {
            "total": len(proxies),
            ProxyHealthState.ACTIVE.value: 0,
            ProxyHealthState.COOLDOWN.value: 0,
            ProxyHealthState.BANNED.value: 0,
        }
        rows = []
        for p in proxies:
            h = hmap.get(p.id, ProxyHealthRecord(proxy_id=p.id))
            summary[h.state] = summary.get(h.state, 0) + 1
            cd_str = ""
            if h.cooldown_until:
                remaining = max(0, h.cooldown_until - time.time())
                cd_str = f"{remaining:.0f}s remaining"
            last_check = (
                time.strftime("%H:%M:%S", time.localtime(h.last_check))
                if h.last_check else "-"
            )
            last_success = (
                time.strftime("%H:%M:%S", time.localtime(h.last_success_at))
                if h.last_success_at else "-"
            )
            last_fail = (
                time.strftime("%H:%M:%S", time.localtime(h.last_failure_at))
                if h.last_failure_at else "-"
            )
            err = h.last_error or ""
            rows.append([
                p.id,
                _proxy_state_emoji(h.state),
                str(h.consecutive_failures),
                str(h.failure_count),
                str(h.success_count),
                f"{h.latency_ms_avg:.0f}" if h.latency_ms_avg > 0 else "-",
                last_check,
                last_success,
                last_fail,
                cd_str,
                err[:40] + "..." if len(err) > 40 else err,
            ])
        return summary, rows

    def _recover_all() -> str:
        hmap = health_store.load_all()
        count = 0
        for p in proxies:
            h = hmap.get(p.id, ProxyHealthRecord(proxy_id=p.id))
            if h.state == ProxyHealthState.COOLDOWN.value:
                h.state = ProxyHealthState.ACTIVE.value
                h.consecutive_failures = 0
                h.cooldown_until = None
                health_store.upsert(h)
                count += 1
        return f"✅ 恢复 {count} 个 COOLDOWN → ACTIVE"

    def _set_state(pid: str, state: str, cooldown_sec: float = 0) -> str:
        if not pid.strip():
            return "⚠️ Proxy ID 不能为空"
        for p in proxies:
            if p.id == pid.strip():
                h = health_store.get(p.id)
                h.state = state
                if state == ProxyHealthState.COOLDOWN.value:
                    h.cooldown_until = time.time() + cooldown_sec
                elif state == ProxyHealthState.ACTIVE.value:
                    h.consecutive_failures = 0
                    h.cooldown_until = None
                health_store.upsert(h)
                return f"✅ {p.id} → {state}"
        return f"❌ 未找到: {pid}"

    def _refresh_preview() -> list[list]:
        rows = []
        for p in proxies:
            try:
                server, username, password = p.get_playwright_proxy()
                rows.append([
                    p.id,
                    p.region or "-",
                    server or "-",
                    username or "-",
                    "***" if password else "-",
                    "✅" if server else "❌",
                ])
            except Exception:
                rows.append([
                    p.id, p.region or "-",
                    "❌ 解析失败", "-", "-", "❌",
                ])
        return rows

    # bind events
    a_btn.click(
        fn=_do_add,
        inputs=[a_url, a_region, a_tags, a_notes],
        outputs=[a_result, t1_table],
    )
    e_save.click(
        fn=_do_save,
        inputs=[e_id, e_url, e_region, e_enabled],
        outputs=[e_result],
    )
    e_del.click(fn=_do_delete, inputs=[e_id], outputs=[e_result])
    t1_batch_btn.click(
        fn=_do_batch_import,
        inputs=[t1_batch_file, t1_batch_format],
        outputs=[t1_batch_result],
    )

    t2_refresh.click(
        fn=_build_health_rows,
        outputs=[t2_summary, t2_table],
    )
    t2_recover_all_btn.click(fn=_recover_all, outputs=[h_result])

    h_cooldown_btn.click(
        fn=lambda pid: _set_state(pid, ProxyHealthState.COOLDOWN.value, 300),
        inputs=[t2_pid],
        outputs=[h_result],
    )
    h_ban_btn.click(
        fn=lambda pid: _set_state(pid, ProxyHealthState.BANNED.value),
        inputs=[t2_pid],
        outputs=[h_result],
    )
    h_active_btn.click(
        fn=lambda pid: _set_state(pid, ProxyHealthState.ACTIVE.value),
        inputs=[t2_pid],
        outputs=[h_result],
    )
    h_reset_btn.click(
        fn=lambda pid: (
            health_store.delete(pid.strip()) if pid.strip() else None,
            f"✅ 重置 {pid} 健康记录" if pid.strip() else "⚠️ Proxy ID 不能为空",
        )[1],
        inputs=[t2_pid],
        outputs=[h_result],
    )

    t3_refresh.click(fn=_refresh_preview, outputs=[t3_table])

    # ── Tab4: 池策略配置 ────────────────────────────────────────────

    gr.Markdown("---")
    gr.Markdown("### ⚙️ 池策略配置")

    from Tools.proxy_backend import (
        set_health_check_interval,
        get_pool_visual_status,
        geoip_route,
    )
    from Core.Profile.pool import _get_pool_instance
    from Core.Profile import AcquireStrategy

    strategy_choices = [s.value for s in AcquireStrategy]

    with gr.Row():
        with gr.Column():
            t4_strategy = gr.Dropdown(
                label="获取策略",
                choices=strategy_choices,
                value=strategy_choices[0],
            )
            t4_max_concurrent = gr.Number(
                label="最大并发数",
                value=10,
                minimum=1,
                maximum=100,
                step=1,
            )
            t4_health_interval = gr.Number(
                label="健康检测间隔（分钟，0=关闭）",
                value=0,
                minimum=0,
                maximum=1440,
                step=1,
            )
            t4_apply_btn = gr.Button("💾 应用策略", variant="primary")
            t4_result = gr.Textbox(label="结果", interactive=False, lines=3)

        with gr.Column():
            t4_geoip_url = gr.Textbox(
                label="GeoIP 路由测试（输入 URL）",
                placeholder="https://www.amazon.co.jp/...",
            )
            t4_geoip_profile = gr.Dropdown(
                label="Profile",
                choices=["default"],
                value="default",
            )
            t4_geoip_result = gr.JSON(label="路由结果", value={})
            t4_geoip_btn = gr.Button("🔍 测试 GeoIP 路由", variant="secondary")

    gr.Markdown("### 📊 池状态总览")

    t4_pool_status = gr.JSON(label="池状态", value={})
    t4_pool_refresh = gr.Button("🔄 刷新池状态", variant="secondary")

    # ── Tab5: 池可视化 ──────────────────────────────────────────────

    gr.Markdown("---")
    gr.Markdown("### 📈 代理池可视化")

    t5_refresh = gr.Button("🔄 刷新可视化", variant="secondary")

    t5_by_state = gr.JSON(label="按状态分布", value={})
    t5_by_region = gr.JSON(label="按地区分布", value={})
    t5_profiles_detail = gr.Dataframe(
        label="各 Profile 代理详情",
        headers=["Profile ID", "总数", "Active", "Cooldown", "Banned", "地区列表"],
        datatype=["str", "number", "number", "number", "number", "str"],
        value=[],
        interactive=False,
    )

    # ── Tab4/Tab5 事件绑定 ────────────────────────────────────────────

    def _apply_strategy(strategy, max_concurrent, health_interval):
        try:
            pool = _get_pool_instance()
            if pool is not None:
                pool.set_strategy(AcquireStrategy(strategy))
                pool.set_max_concurrent(int(max_concurrent))
                pool.set_health_check_interval(int(health_interval))
                return f"✅ 策略已更新\n策略: {strategy}\n并发: {max_concurrent}\n健康检测: {health_interval}min"
            return "⚠️ Pool 未初始化（先启动 ProfilePool）"
        except Exception as e:
            return f"❌ 错误: {e}"

    def _refresh_pool_status():
        try:
            vs = get_pool_visual_status()
            pool = _get_pool_instance()
            if pool is not None:
                vs["strategy"] = pool.strategy.value
                vs["max_concurrent"] = pool._semaphore._value
                vs["health_check_interval_minutes"] = pool._health_check_interval
            return vs
        except Exception as e:
            return {"error": str(e)}

    def _do_geoip_route(url, profile_id):
        try:
            result = geoip_route(url, profile_id)
            if result is None:
                return {"matched": False, "message": "无可用代理（无匹配 region 或池为空）"}
            return result
        except Exception as e:
            return {"error": str(e)}

    def _refresh_visualization():
        try:
            vs = get_pool_visual_status()
            return vs.get("by_state", {}), vs.get("by_region", {}), _profiles_detail_rows(vs)
        except Exception as e:
            return {"error": str(e)}, {}, []

    def _profiles_detail_rows(vs):
        rows = []
        for p in vs.get("profiles", []):
            rows.append([
                p["profile_id"],
                p["total"],
                p["active"],
                p["cooldown"],
                p["banned"],
                ", ".join(p.get("regions", [])) or "-",
            ])
        return rows

    t4_apply_btn.click(
        fn=_apply_strategy,
        inputs=[t4_strategy, t4_max_concurrent, t4_health_interval],
        outputs=[t4_result],
    )
    t4_pool_refresh.click(fn=_refresh_pool_status, outputs=[t4_pool_status])
    t4_geoip_btn.click(fn=_do_geoip_route, inputs=[t4_geoip_url, t4_geoip_profile], outputs=[t4_geoip_result])
    t5_refresh.click(
        fn=_refresh_visualization,
        inputs=[],
        outputs=[t5_by_state, t5_by_region, t5_profiles_detail],
    )
