"""Proxy 管理 Web 面板 (Gradio).

启动: python -m Tools.proxy_panel
端口: 7863 (--port 可改)

三个 Tab:
  Tab1: 代理列表 + 单条增删改 + 批量导入
  Tab2: 健康面板（state 图标 + 失败次数 + 延迟 + 一键 cooldown 恢复）
  Tab3: 用法展示（Playwright proxy 三元组示例）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.ProxyPool.proxy import Proxy
from Core.ProxyPool.health import ProxyHealthStore, ProxyHealthRecord, ProxyHealthState


# ─── 全局后端 ────────────────────────────────────────────────────

_health_store: ProxyHealthStore | None = None
_proxy_list: list[Proxy] | None = None


def _get_health_store() -> ProxyHealthStore:
    global _health_store
    if _health_store is None:
        _health_store = ProxyHealthStore()
    return _health_store


def _get_proxy_list() -> list[Proxy]:
    """内存态代理列表（模拟全局代理池）"""
    global _proxy_list
    if _proxy_list is None:
        _proxy_list = []
    return _proxy_list


# ─── 数据格式化 ─────────────────────────────────────────────────

_URL_AUTH_RE = re.compile(
    r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*)://"
    r"((?P<user>[^:@]+):(?P<pass>[^@]+)@)?"
    r"(?P<host>[^/@]+)"
    r"(?P<path>/.*)?$"
)


def _parse_proxy_url(url: str) -> dict:
    """解析代理 URL，返回 scheme/host/port/user/pass"""
    m = _URL_AUTH_RE.match(url.strip())
    if not m:
        return {"url": url, "scheme": "http", "host": url, "port": "", "user": "", "pass": ""}
    scheme = m.group("scheme") or "http"
    host = m.group("host") or ""
    user = m.group("user") or ""
    pw = m.group("pass") or ""
    if ":" in host and not host.startswith("["):
        parts = host.rsplit(":", 1)
        host = parts[0]
        port = parts[1]
    else:
        port = "80" if scheme == "http" else "8080"
    return {"url": url, "scheme": scheme, "host": host, "port": port, "user": user, "pass": pw}


def _proxy_state_emoji(state: str) -> str:
    return {
        ProxyHealthState.ACTIVE.value: "🟢 ACTIVE",
        ProxyHealthState.COOLDOWN.value: "🟡 COOLDOWN",
        ProxyHealthState.BANNED.value: "🔴 BANNED",
    }.get(state, "⚪ UNKNOWN")


def _proxy_to_row(p: Proxy, health: ProxyHealthRecord) -> list[Any]:
    """Proxy + health → Dataframe 行"""
    cooldown_str = ""
    if health.state == ProxyHealthState.COOLDOWN.value and health.cooldown_until:
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
        f"{health.consecutive_failures}",
        f"{health.failure_count}",
        f"{health.success_count}",
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


# ─── UI ────────────────────────────────────────────────────────

def _build_ui():
    import gradio as gr

    health_store = _get_health_store()

    with gr.Blocks(title="WebAuto Proxy 管理面板") as demo:
        gr.Markdown("# 🌐 WebAuto Proxy 管理面板")
        gr.Markdown(
            "管理代理池，支持单条增删改、批量导入、健康追踪。"
        )

        # ═══════════════════════════════════════════════════════
        # Tab 1: 代理 CRUD + 批量导入
        # ═══════════════════════════════════════════════════════
        with gr.Tab("代理列表"):
            gr.Markdown("### 所有代理（🟢可用 🟡冷却 🔴封禁）")

            with gr.Row():
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

            gr.Markdown("---")
            gr.Markdown("### ➕ 添加代理")

            with gr.Row():
                with gr.Column():
                    t1_add_url = gr.Textbox(
                        label="代理 URL",
                        placeholder="http://user:pass@host:port",
                    )
                    t1_add_region = gr.Textbox(
                        label="Region（ISO，如 CN/US/JP）",
                        placeholder="US",
                    )
                    t1_add_tags = gr.Textbox(
                        label="标签（逗号分隔）",
                        placeholder="residential, datacenter",
                    )
                    t1_add_notes = gr.Textbox(
                        label="备注",
                        placeholder="可选备注",
                    )
                    t1_add_btn = gr.Button("✅ 添加代理", variant="primary")

                with gr.Column():
                    t1_add_result = gr.Textbox(
                        label="操作结果",
                        interactive=False,
                        lines=5,
                    )

            gr.Markdown("---")
            gr.Markdown("### ✏️ 编辑 / 🗑️ 删除")

            with gr.Row():
                with gr.Column():
                    t1_edit_id = gr.Textbox(
                        label="Proxy ID（要编辑/删除的）",
                    )
                    t1_edit_url = gr.Textbox(
                        label="新 URL（不改留空）",
                    )
                    t1_edit_region = gr.Textbox(
                        label="新 Region（不改留空）",
                    )
                    t1_edit_enabled = gr.Checkbox(
                        label="启用",
                        value=True,
                    )
                    with gr.Row():
                        t1_save_btn = gr.Button("💾 保存", variant="primary")
                        t1_del_btn = gr.Button("🗑️ 删除", variant="stop")
                    t1_edit_result = gr.Textbox(
                        label="操作结果",
                        interactive=False,
                        lines=3,
                    )

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

            # ── 事件绑定 ─────────────────────────────────────

            def _refresh():
                return _all_rows()

            def _do_add(url: str, region: str, tags_str: str, notes: str) -> str:
                if not url.strip():
                    return "⚠️ URL 不能为空"
                proxies = _get_proxy_list()
                parsed = _parse_proxy_url(url.strip())
                proxy = Proxy(
                    id=f"proxy-{uuid.uuid4().hex[:8]}",
                    url=url.strip(),
                    region=region.strip().upper() if region.strip() else None,
                    tags=[t.strip() for t in tags_str.split(",") if t.strip()],
                    notes=notes.strip(),
                    enabled=True,
                )
                # 解析出 username/password
                if parsed.get("user"):
                    proxy.username = parsed["user"]
                if parsed.get("pass"):
                    proxy.password = parsed["pass"]
                proxies.append(proxy)
                # 初始化健康记录
                health_store.upsert(ProxyHealthRecord(proxy_id=proxy.id))
                return f"✅ 添加成功: {proxy.id}\nURL: {proxy.url}\nRegion: {proxy.region or '-'}"

            def _do_save(
                pid: str, new_url: str, new_region: str, enabled: bool,
            ) -> str:
                if not pid.strip():
                    return "⚠️ Proxy ID 不能为空"
                proxies = _get_proxy_list()
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
                proxies = _get_proxy_list()
                for i, p in enumerate(proxies):
                    if p.id == pid.strip():
                        proxies.pop(i)
                        health_store.delete(pid.strip())
                        return f"✅ 已删除: {pid}"
                return f"❌ 未找到 Proxy: {pid}"

            def _do_batch_import(file_path: str, fmt: str) -> str:
                if not file_path:
                    return "⚠️ 请先上传文件"
                proxies = _get_proxy_list()
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        raw = f.read().strip()

                    if fmt.startswith("纯文本"):
                        # 每行一个 URL
                        lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.startswith("#")]
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
                        # JSON
                        data = json.loads(raw)
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

            t1_refresh.click(fn=_refresh, outputs=t1_table)
            t1_add_btn.click(
                fn=_do_add,
                inputs=[t1_add_url, t1_add_region, t1_add_tags, t1_add_notes],
                outputs=t1_add_result,
            )
            t1_save_btn.click(
                fn=_do_save,
                inputs=[t1_edit_id, t1_edit_url, t1_edit_region, t1_edit_enabled],
                outputs=t1_edit_result,
            )
            t1_del_btn.click(fn=_do_delete, inputs=[t1_edit_id], outputs=t1_edit_result)
            t1_batch_btn.click(
                fn=_do_batch_import,
                inputs=[t1_batch_file, t1_batch_format],
                outputs=t1_batch_result,
            )

        # ═══════════════════════════════════════════════════════
        # Tab 2: 健康面板
        # ═══════════════════════════════════════════════════════
        with gr.Tab("健康面板"):
            gr.Markdown("### 代理健康状态")

            with gr.Row():
                t2_refresh = gr.Button("🔄 刷新", variant="secondary")
                t2_recover_all_btn = gr.Button("🔁 一键恢复全部 COOLDOWN → ACTIVE", variant="secondary")

            with gr.Row():
                t2_summary = gr.JSON(
                    label="汇总统计",
                    value={},
                )

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
                    with gr.Row():
                        t2_cooldown_btn = gr.Button(
                            "🔸 标记 COOLDOWN（n秒）",
                            variant="stop",
                        )
                        t2_ban_btn = gr.Button("🔴 标记 BANNED", variant="stop")
                        t2_active_btn = gr.Button("🟢 标记 ACTIVE", variant="primary")
                        t2_reset_btn = gr.Button("🔄 重置健康记录", variant="secondary")
                    t2_health_result = gr.Textbox(
                        label="操作结果",
                        interactive=False,
                        lines=3,
                    )

            # ── 事件绑定 ─────────────────────────────────────

            def _build_health_rows() -> tuple[dict, list[list]]:
                proxies = _get_proxy_list()
                health_map = health_store.load_all()
                summary = {"total": len(proxies), "active": 0, "cooldown": 0, "banned": 0}
                rows = []
                for p in proxies:
                    h = health_map.get(p.id, ProxyHealthRecord(proxy_id=p.id))
                    summary[h.state] = summary.get(h.state, 0) + 1
                    if h.state == ProxyHealthState.ACTIVE.value:
                        summary["active"] += 1
                    elif h.state == ProxyHealthState.COOLDOWN.value:
                        summary["cooldown"] += 1
                    elif h.state == ProxyHealthState.BANNED.value:
                        summary["banned"] += 1
                    cd_str = ""
                    if h.cooldown_until:
                        remaining = max(0, h.cooldown_until - time.time())
                        cd_str = f"{remaining:.0f}s remaining"
                    last_check = time.strftime("%H:%M:%S", time.localtime(h.last_check)) if h.last_check else "-"
                    last_success = time.strftime("%H:%M:%S", time.localtime(h.last_success_at)) if h.last_success_at else "-"
                    last_fail = time.strftime("%H:%M:%S", time.localtime(h.last_failure_at)) if h.last_failure_at else "-"
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
                        h.last_error[:40] + "..." if h.last_error and len(h.last_error) > 40 else h.last_error or "",
                    ])
                return summary, rows

            def _recover_all() -> str:
                proxies = _get_proxy_list()
                health_map = health_store.load_all()
                count = 0
                for p in proxies:
                    h = health_map.get(p.id, ProxyHealthRecord(proxy_id=p.id))
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
                proxies = _get_proxy_list()
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

            t2_refresh.click(
                fn=_build_health_rows,
                outputs=[t2_summary, t2_table],
            )
            t2_recover_all_btn.click(fn=_recover_all, outputs=[t2_health_result])
            t2_active_btn.click(
                fn=lambda pid: _set_state(pid, ProxyHealthState.ACTIVE.value),
                inputs=[t2_pid],
                outputs=[t2_health_result],
            )
            t2_ban_btn.click(
                fn=lambda pid: _set_state(pid, ProxyHealthState.BANNED.value),
                inputs=[t2_pid],
                outputs=[t2_health_result],
            )
            t2_cooldown_btn.click(
                fn=lambda pid: _set_state(pid, ProxyHealthState.COOLDOWN.value, 300),
                inputs=[t2_pid],
                outputs=[t2_health_result],
            )
            t2_reset_btn.click(
                fn=lambda pid: (
                    health_store.delete(pid.strip()) if pid.strip() else None,
                    f"✅ 重置 {pid} 健康记录" if pid.strip() else "⚠️ Proxy ID 不能为空",
                )[1],
                inputs=[t2_pid],
                outputs=[t2_health_result],
            )

        # ═══════════════════════════════════════════════════════
        # Tab 3: Playwright proxy 用法
        # ═══════════════════════════════════════════════════════
        with gr.Tab("Playwright 用法"):
            gr.Markdown("### Playwright Proxy 三元组示例")

            gr.Markdown("""
**Proxy 三元组格式**（用于 `browser.new_context(proxy=...)`）:

```python
proxy = {
    "server": "http://host:port",   # 无认证 URL
    "username": "user",             # 认证用户（无认证则省略）
    "password": "pass",            # 认证密码（无认证则省略）
}
```

**从 Profile.network 获取三元组（推荐）：**

```python
from Core.Profile.profile import Profile, NetworkConfig

net = NetworkConfig(
    proxy_url="http://user:pass@proxy.example.com:8080",
)
server, username, password = net.get_playwright_proxy()
# server   = "http://proxy.example.com:8080"
# username = "user"
# password = "pass"

context = await browser.new_context(proxy={"server": server, "username": username, "password": password})
```

**直接从 Proxy 对象获取三元组：**

```python
from Core.ProxyPool.proxy import Proxy

p = Proxy(
    id="proxy-001",
    url="http://user:pass@proxy.example.com:8080",
    region="US",
    tags=["residential"],
)

# Proxy.get_playwright_proxy() 返回三元组
server, username, password = p.get_playwright_proxy()
```

**注意事项：**
- `server` 必须是完整 URL（`http://` 或 `socks5://` 前缀不能省略）
- `username`/`password` 为 `None` 时不要传
- 住宅代理推荐 `socks5` 协议
- 建议配合 `ProxyRotator` 做失败自动轮换
            """)

            gr.Markdown("---")
            gr.Markdown("### 当前代理池三元组预览")

            with gr.Row():
                t3_refresh = gr.Button("🔄 刷新预览", variant="secondary")
                t3_table = gr.Dataframe(
                    headers=["Proxy ID", "Region", "server", "username", "password", "已解析"],
                    datatype=["str"] * 6,
                    value=[],
                    interactive=False,
                )

            def _refresh_preview() -> list[list]:
                proxies = _get_proxy_list()
                rows = []
                for p in proxies:
                    try:
                        server, username, password = p.get_playwright_proxy()
                        rows.append([
                            p.id,
                            p.region or "-",
                            server or "-",
                            username or "-",
                            password and "***" or "-",
                            "✅" if server else "❌",
                        ])
                    except Exception:
                        rows.append([p.id, p.region or "-", "❌ 解析失败", "-", "-", "❌"])
                return rows

            t3_refresh.click(fn=_refresh_preview, outputs=t3_table)

    return demo


def main():
    parser = argparse.ArgumentParser(description="WebAuto Proxy 管理面板")
    parser.add_argument("--port", type=int, default=7863, help="监听端口")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--share", action="store_true", help="生成 Gradio 分享链接")
    args = parser.parse_args()

    demo = _build_ui()
    print(f"🚀 启动 Proxy 面板 → http://{args.host}:{args.port}")
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
    )


if __name__ == "__main__":
    main()
