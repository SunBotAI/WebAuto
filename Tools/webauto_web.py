"""WebAuto 统一 Web 面板 (Gradio).

启动: python Tools/webauto_web.py
端口: 7860 (--port 可改)

四个 Tab:
  Tab1: Console（抢购控制台）
  Tab2: 智谱凭证（credential_panel）
  Tab3: Profile 管理（profile_panel）
  Tab4: Proxy 管理（proxy_panel）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ─── 模块导入（延迟，避免端口冲突）──────────────────────────────────

# credential_panel 会有自己的 demo.launch，
# 所以我们只 import backend 类，自己 build UI
# 注意：CredentialBackend 导入链较重（curl_cffi 等），在 Tab 内延迟 import


def _build_credential_tab():
    """构造凭证管理 Tab（从 credential_panel.py 的 UI 逻辑重构）"""
    import asyncio
    import gradio as gr
    from Tools.credential_backend import CredentialBackend
    backend = CredentialBackend(
        secret_store_path=".secrets.enc",
        key_env="GLM_GRABBER_KEY",
        ask=False,
    )

    def _run(coro):
        try:
            loop = asyncio.new_event_loop()
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def _format_check_result(result: dict) -> str:
        lines = []
        lines.append("✅ 成功" if result.get("success") else "❌ 失败")
        if result.get("message"):
            lines.append(result["message"])
        if result.get("user_id"):
            lines.append(f"user_id: {result['user_id']}")
        if result.get("customer_number"):
            lines.append(f"customer_number: {result['customer_number']}")
        if result.get("expires_hint"):
            lines.append(f"提示: {result['expires_hint']}")
        return "\n".join(lines)

    def _format_sms_result(result: dict) -> str:
        stage = result.get("stage", "unknown")
        success = result.get("success", False)
        if stage == "code_sent":
            return f"📤 {result.get('message', '验证码已发送')}"
        if stage == "done":
            prefix = "✅ 登录成功" if success else "❌ 登录失败"
            msg = result.get("message", "")
            uid = result.get("user_id", "")
            out = f"{prefix}\n{msg}"
            if uid:
                out += f"\nuser_id: {uid}"
            return out
        return f"⚠️ {result.get('message', '未知阶段')}"

    def _accounts_to_rows(accounts: list[dict]) -> list[list]:
        if not accounts:
            return [[]] * 6
        return [
            [
                a.get("name", ""),
                a.get("phone", ""),
                a.get("user_id", ""),
                a.get("saved_at", ""),
                "✅" if a.get("has_token") else "❌",
                "✅" if a.get("has_cookie") else "❌",
            ]
            for a in accounts
        ]

    gr.Markdown("### 凭证管理")

    # Tab 1: 粘贴 Token
    with gr.Tab("粘贴 Token / Cookie"):
        gr.Markdown("把浏览器 F12 抓的 Authorization / Cookie 粘进下面，点验证并保存")
        with gr.Row():
            with gr.Column():
                t1_name = gr.Textbox(label="账号名", placeholder="主账号", value="主账号")
                t1_phone = gr.Textbox(label="手机号", placeholder="138xxxxxxxx")
                t1_token = gr.Textbox(
                    label="Bearer Token (从 Authorization 头取)",
                    placeholder="eyJhbGciOiJIUzI1NiIs...",
                    type="password",
                )
                t1_cookie = gr.Textbox(
                    label="Cookie (可选)",
                    placeholder="atlas_t=xxx; _bl_uid=xxx; ...",
                    lines=4,
                )
                t1_btn = gr.Button("✅ 验证并保存", variant="primary")
            with gr.Column():
                t1_result = gr.Textbox(label="结果", interactive=False, lines=8)
        t1_btn.click(
            fn=lambda name, phone, token, cookie: _format_check_result(
                _run(backend.check_and_save(name, phone, token, cookie))
            ),
            inputs=[t1_name, t1_phone, t1_token, t1_cookie],
            outputs=t1_result,
        )

    # Tab 2: 短信登录
    with gr.Tab("短信登录"):
        gr.Markdown(
            "用智谱账密 + 短信验证码登录\n"
            "第一步：填账号名 + 手机号，点发送验证码\n"
            "第二步：看到短信后填入验证码，点登录并保存"
        )
        with gr.Row():
            with gr.Column():
                t2_name = gr.Textbox(label="账号名", value="主账号")
                t2_phone = gr.Textbox(label="手机号", placeholder="138xxxxxxxx")
                with gr.Row():
                    t2_send_btn = gr.Button("📤 发送验证码", variant="primary")
                    t2_resend_btn = gr.Button("🔁 重发验证码")
                t2_sms_status = gr.Textbox(
                    label="短信状态", value="(未发送)", interactive=False, lines=2,
                )
                t2_code = gr.Textbox(
                    label="短信验证码(6 位数字)",
                    placeholder="短信里的 6 位数字",
                    max_lines=1,
                )
                t2_login_btn = gr.Button("✅ 登录并保存", variant="primary")
            with gr.Column():
                t2_result = gr.Textbox(label="结果", interactive=False, lines=10)

        sms_state = gr.State(value={"code_sent": False, "phone": "", "name": ""})

        def _do_send_code(name, phone, state):
            if not phone.strip():
                return "⚠️ 请先填写手机号", state
            result = _run(backend.login_by_sms(name, phone))
            new_state = dict(state)
            new_state["code_sent"] = result.get("stage") == "code_sent"
            new_state["phone"] = phone
            new_state["name"] = name
            return _format_sms_result(result), new_state

        def _do_login(name, phone, code, state):
            if not code.strip():
                return "⚠️ 请先填写 6 位短信验证码", state
            if not phone.strip():
                return "⚠️ 手机号不能为空", state
            if state.get("phone") and state["phone"] != phone:
                return f"⚠️ 你改了手机号，需要重新点发送验证码", state
            result = _run(backend.login_by_sms(name, phone, sms_code=code))
            if result.get("success"):
                new_state = {"code_sent": False, "phone": "", "name": ""}
            else:
                new_state = state
            return _format_sms_result(result), new_state

        t2_send_btn.click(
            fn=_do_send_code,
            inputs=[t2_name, t2_phone, sms_state],
            outputs=[t2_sms_status, sms_state],
        )
        t2_resend_btn.click(
            fn=_do_send_code,
            inputs=[t2_name, t2_phone, sms_state],
            outputs=[t2_sms_status, sms_state],
        )
        t2_login_btn.click(
            fn=_do_login,
            inputs=[t2_name, t2_phone, t2_code, sms_state],
            outputs=[t2_result, sms_state],
        )

    # Tab 3: 已保存账号
    with gr.Tab("已保存账号"):
        gr.Markdown("加密凭证库里已保存的账号（token/cookie 不显示，仅元数据）")
        t3_refresh = gr.Button("🔄 刷新列表")
        t3_table = gr.Dataframe(
            headers=["账号名", "手机号(脱敏)", "user_id", "保存时间", "有 token", "有 cookie"],
            datatype=["str"] * 6,
            value=_accounts_to_rows(_run(backend.list_accounts())),
            interactive=False,
        )
        t3_refresh.click(
            fn=lambda: _accounts_to_rows(_run(backend.list_accounts())),
            outputs=t3_table,
        )
        with gr.Row():
            t3_del_name = gr.Textbox(label="要删除的账号名", placeholder="主账号")
            t3_del_btn = gr.Button("🗑️ 删除", variant="stop")
            t3_del_result = gr.Textbox(label="删除结果", interactive=False)
        t3_del_btn.click(
            fn=lambda name: _run(backend.delete_account(name)).get("message", "操作完成"),
            inputs=t3_del_name,
            outputs=t3_del_result,
        )


def _build_profile_tab():
    """构造 Profile 管理 Tab"""
    import asyncio
    import gradio as gr
    import uuid

    from Core.Profile.profile import Profile, ProfileStatus
    from Core.Profile.store import ProfileStore
    from Core.Profile.pool import ProfilePool, AcquireStrategy
    from Core.Profile.fingerprint_gen import FingerprintGenerator, UA_TEMPLATES, PLATFORM_MAP

    def _run(coro):
        try:
            loop = asyncio.new_event_loop()
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    _store = ProfileStore()
    _pool = ProfilePool(_store, strategy=AcquireStrategy.LEAST_USED, max_concurrent=5)

    def _profile_status_emoji(status: ProfileStatus) -> str:
        return {
            ProfileStatus.READY: "🟢 READY",
            ProfileStatus.RUNNING: "🔵 RUNNING",
            ProfileStatus.COOLDOWN: "🟡 COOLDOWN",
            ProfileStatus.BANNED: "🔴 BANNED",
            ProfileStatus.ARCHIVED: "⚪ ARCHIVED",
        }.get(status, str(status))

    def _profile_to_row(p: Profile) -> list:
        cooldown_str = ""
        if p.status == ProfileStatus.COOLDOWN and p.cooldown_until:
            import time
            remaining = max(0, p.cooldown_until - time.time())
            cooldown_str = f"{remaining:.0f}s"
        return [
            p.id, p.name,
            ",".join(p.tags) if p.tags else "",
            _profile_status_emoji(p.status),
            cooldown_str,
            p.network.proxy_url or "",
            p.fingerprint.user_agent[:40] + "..." if len(p.fingerprint.user_agent) > 40 else p.fingerprint.user_agent,
        ]

    def _refresh_list():
        return [_profile_to_row(p) for p in _store.list_all()]

    gr.Markdown("### Profile 管理")

    with gr.Row():
        with gr.Column(scale=2):
            t1_refresh = gr.Button("🔄 刷新列表", variant="secondary")
            t1_table = gr.Dataframe(
                headers=["ID", "名称", "标签", "状态", "CD剩余", "代理", "UA(截断)"],
                datatype=["str"] * 7,
                value=_refresh_list(),
                interactive=False,
                max_height=280,
            )
        with gr.Column(scale=1):
            t1_detail = gr.Markdown("**👆 点预览按钮查看指纹详情**")

    selected_id = gr.State(value=None)


    def _preview(pid):
        if not pid:
            return "**👆 点预览按钮查看指纹详情**"
        try:
            p = _store.get(pid)
            fp = p.fingerprint
            return (
                f"**UA:**\n```\n{fp.user_agent}\n```\n"
                f"**Platform:** {fp.platform}\n"
                f"**Locale:** {fp.locale}\n"
                f"**Timezone:** {fp.timezone}\n"
                f"**Screen:** {fp.screen_resolution}\n"
                f"**Canvas Seed:** {fp.canvas_seed}\n"
                f"**Proxy:** {p.network.proxy_url or '(无)'}"
            )
        except FileNotFoundError:
            return f"❌ Profile {pid} 不存在"

    t1_refresh.click(fn=_refresh_list, outputs=t1_table)

    with gr.Row():
        t1_preview_btn = gr.Button("🔍 预览指纹", variant="secondary")
        t1_preview_btn.click(fn=_preview, inputs=[selected_id], outputs=[t1_detail])

    gr.Markdown("---")
    gr.Markdown("### ➕ 创建 Profile")

    with gr.Row():
        with gr.Column():
            c_name = gr.Textbox(label="名称", placeholder="e.g. 主账号-US")
            c_tags = gr.Textbox(label="标签（逗号分隔）", placeholder="US, residential", value="default")
            c_ua = gr.Dropdown(
                label="UA 类型", choices=list(UA_TEMPLATES.keys()), value="linux_chrome_120",
            )
            c_proxy = gr.Textbox(label="代理 URL（可选）", placeholder="http://user:pass@host:port")
            c_locale = gr.Textbox(label="Locale", value="en-US")
            c_tz = gr.Textbox(label="Timezone", value="America/New_York")
            c_btn = gr.Button("✅ 创建 Profile", variant="primary")
        with gr.Column():
            c_result = gr.Textbox(label="操作结果", interactive=False, lines=5)

    def _do_create(name, tags_str, ua_type, proxy, locale, tz):
        if not name.strip():
            return "⚠️ 名称不能为空", _refresh_list()
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        ua_choices = UA_TEMPLATES.get(ua_type, UA_TEMPLATES["linux_chrome_120"])
        gen = FingerprintGenerator()
        fp = gen.generate(template=ua_type)
        fp.user_agent = ua_choices[0]
        fp.platform = PLATFORM_MAP.get(ua_type, "Linux x86_64")
        fp.locale = locale
        fp.timezone = tz
        from Core.Profile.profile import NetworkConfig
        net = NetworkConfig()
        if proxy.strip():
            net.proxy_url = proxy.strip()
        profile = Profile(name=name.strip(), tags=tags, fingerprint=fp, network=net)
        try:
            _store.create(profile)
            return f"✅ 创建成功: {profile.id}", _refresh_list()
        except Exception as e:
            return f"❌ 创建失败: {e}", _refresh_list()

    c_btn.click(
        fn=_do_create,
        inputs=[c_name, c_tags, c_ua, c_proxy, c_locale, c_tz],
        outputs=[c_result, t1_table],
    )

    gr.Markdown("---")
    gr.Markdown("### ✏️ 编辑 / 🗑️ 删除")

    with gr.Row():
        with gr.Column():
            e_id = gr.Textbox(label="Profile ID")
            e_name = gr.Textbox(label="新名称（不改留空）")
            e_tags = gr.Textbox(label="新标签（不改留空）")
            e_proxy = gr.Textbox(label="新代理 URL（不改留空）")
            with gr.Row():
                e_save = gr.Button("💾 保存", variant="primary")
                e_del = gr.Button("🗑️ 删除", variant="stop")
            e_result = gr.Textbox(label="结果", interactive=False, lines=3)

    def _do_save(pid, name, tags, proxy):
        if not pid.strip():
            return "⚠️ ID 不能为空"
        try:
            p = _store.get(pid.strip())
        except FileNotFoundError:
            return f"❌ Profile {pid} 不存在"
        if name.strip():
            p.name = name.strip()
        if tags.strip():
            p.tags = [t.strip() for t in tags.split(",") if t.strip()]
        if proxy.strip():
            p.network.proxy_url = proxy.strip()
        try:
            _store.save(p)
            return f"✅ 已保存: {p.id}"
        except Exception as e:
            return f"❌ 保存失败: {e}"

    def _do_delete(pid):
        if not pid.strip():
            return "⚠️ ID 不能为空"
        try:
            _store.delete(pid.strip())
            return f"✅ 已删除: {pid}"
        except Exception as e:
            return f"❌ 删除失败: {e}"

    e_save.click(fn=_do_save, inputs=[e_id, e_name, e_tags, e_proxy], outputs=[e_result])
    e_del.click(fn=_do_delete, inputs=[e_id], outputs=[e_result])


def _build_proxy_tab():
    """构造 Proxy 管理 Tab"""
    import gradio as gr
    import json as _json
    import re
    import time
    import uuid

    from Core.ProxyPool.proxy import Proxy
    from Core.ProxyPool.health import ProxyHealthStore, ProxyHealthRecord, ProxyHealthState

    _health_store = ProxyHealthStore()
    _proxies: list[Proxy] = []

    _URL_RE = re.compile(
        r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*)://"
        r"((?P<user>[^:@]+):(?P<pass>[^@]+)@)?"
        r"(?P<host>[^/@]+)"
        r"(?P<path>/.*)?$"
    )

    def _parse(url):
        m = _URL_RE.match(url.strip())
        if not m:
            return dict(url=url, scheme="http", host=url, user="", pass_="")
        scheme = m.group("scheme") or "http"
        host = m.group("host") or ""
        user = m.group("user") or ""
        pw = m.group("pass") or ""
        if ":" in host and not host.startswith("["):
            parts = host.rsplit(":", 1)
            host, port = parts[0], parts[1]
        else:
            port = "80" if scheme == "http" else "8080"
        return dict(url=url, scheme=scheme, host=host, user=user, pass_=pw)

    def _state_emoji(state):
        return {
            ProxyHealthState.ACTIVE.value: "🟢 ACTIVE",
            ProxyHealthState.COOLDOWN.value: "🟡 COOLDOWN",
            ProxyHealthState.BANNED.value: "🔴 BANNED",
        }.get(state, "⚪ UNKNOWN")

    def _all_rows():
        hmap = _health_store.load_all()
        rows = []
        for p in _proxies:
            h = hmap.get(p.id, ProxyHealthRecord(proxy_id=p.id))
            cd = ""
            if h.state == ProxyHealthState.COOLDOWN.value and h.cooldown_until:
                remaining = max(0, h.cooldown_until - time.time())
                cd = f"{remaining:.0f}s"
            lat = f"{h.latency_ms_avg:.0f}ms" if h.latency_ms_avg > 0 else "-"
            rows.append([
                p.id, p.region or "", p.url[:40] + "..." if len(p.url) > 40 else p.url,
                ",".join(p.tags) if p.tags else "",
                "✅" if p.enabled else "❌",
                _state_emoji(h.state),
                str(h.consecutive_failures),
                str(h.failure_count),
                str(h.success_count),
                lat, cd,
            ])
        return rows

    gr.Markdown("### Proxy 管理")

    t1_refresh = gr.Button("🔄 刷新列表", variant="secondary")
    t1_table = gr.Dataframe(
        headers=["ID", "Region", "URL(截断)", "标签", "启用", "状态", "连败", "总失败", "总成功", "延迟", "CD剩余"],
        datatype=["str"] * 11,
        value=_all_rows(),
        interactive=False,
        max_height=280,
    )
    t1_refresh.click(fn=_all_rows, outputs=t1_table)

    gr.Markdown("---")
    gr.Markdown("### ➕ 添加 / ✏️ 编辑")

    with gr.Row():
        with gr.Column():
            a_url = gr.Textbox(label="代理 URL", placeholder="http://user:pass@host:port")
            a_region = gr.Textbox(label="Region（ISO）", placeholder="US")
            a_tags = gr.Textbox(label="标签（逗号分隔）", placeholder="residential")
            a_btn = gr.Button("✅ 添加", variant="primary")
            a_result = gr.Textbox(label="结果", interactive=False, lines=3)
        with gr.Column():
            e_id = gr.Textbox(label="Proxy ID（编辑/删除）")
            e_enabled = gr.Checkbox(label="启用", value=True)
            with gr.Row():
                e_save = gr.Button("💾 保存", variant="primary")
                e_del = gr.Button("🗑️ 删除", variant="stop")
            e_result = gr.Textbox(label="结果", interactive=False, lines=3)

    def _add(url, region, tags_str):
        if not url.strip():
            return "⚠️ URL 不能为空", _all_rows()
        parsed = _parse(url.strip())
        p = Proxy(
            id=f"proxy-{uuid.uuid4().hex[:8]}",
            url=url.strip(),
            region=region.strip().upper() if region.strip() else None,
            tags=[t.strip() for t in tags_str.split(",") if t.strip()],
            enabled=True,
        )
        if parsed.get("user"):
            p.username = parsed["user"]
        if parsed.get("pass"):
            p.password = parsed["pass"]
        _proxies.append(p)
        _health_store.upsert(ProxyHealthRecord(proxy_id=p.id))
        return f"✅ 添加: {p.id}", _all_rows()

    def _save(pid, enabled):
        if not pid.strip():
            return "⚠️ ID 不能为空"
        for p in _proxies:
            if p.id == pid.strip():
                p.enabled = enabled
                return f"✅ 已保存: {p.id}"
        return f"❌ 未找到: {pid}"

    def _delete(pid):
        if not pid.strip():
            return "⚠️ ID 不能为空"
        for i, p in enumerate(_proxies):
            if p.id == pid.strip():
                _proxies.pop(i)
                _health_store.delete(pid.strip())
                return f"✅ 已删除: {pid}"
        return f"❌ 未找到: {pid}"

    a_btn.click(fn=_add, inputs=[a_url, a_region, a_tags], outputs=[a_result, t1_table])
    e_save.click(fn=_save, inputs=[e_id, e_enabled], outputs=[e_result])
    e_del.click(fn=_delete, inputs=[e_id], outputs=[e_result])

    gr.Markdown("---")
    gr.Markdown("### 🔧 健康操作（选中上表 ID）")

    with gr.Row():
        h_pid = gr.Textbox(label="Proxy ID")
        h_cooldown_btn = gr.Button("🔸 标记 COOLDOWN(300s)", variant="stop")
        h_ban_btn = gr.Button("🔴 标记 BANNED", variant="stop")
        h_active_btn = gr.Button("🟢 标记 ACTIVE", variant="primary")
        h_recover_btn = gr.Button("🔁 恢复全部 COOLDOWN", variant="secondary")
        h_result = gr.Textbox(label="结果", interactive=False, lines=2)

    def _set_state(pid, state, cooldown=0):
        if not pid.strip():
            return "⚠️ ID 不能为空"
        for p in _proxies:
            if p.id == pid.strip():
                h = _health_store.get(p.id)
                h.state = state
                if state == ProxyHealthState.COOLDOWN.value:
                    h.cooldown_until = time.time() + cooldown
                elif state == ProxyHealthState.ACTIVE.value:
                    h.consecutive_failures = 0
                    h.cooldown_until = None
                _health_store.upsert(h)
                return f"✅ {p.id} → {state}"
        return f"❌ 未找到: {pid}"

    def _recover_all():
        count = 0
        for p in _proxies:
            h = _health_store.get(p.id)
            if h.state == ProxyHealthState.COOLDOWN.value:
                h.state = ProxyHealthState.ACTIVE.value
                h.consecutive_failures = 0
                h.cooldown_until = None
                _health_store.upsert(h)
                count += 1
        return f"✅ 恢复 {count} 个 → ACTIVE"

    h_cooldown_btn.click(fn=lambda pid: _set_state(pid, ProxyHealthState.COOLDOWN.value, 300), inputs=[h_pid], outputs=[h_result])
    h_ban_btn.click(fn=lambda pid: _set_state(pid, ProxyHealthState.BANNED.value), inputs=[h_pid], outputs=[h_result])
    h_active_btn.click(fn=lambda pid: _set_state(pid, ProxyHealthState.ACTIVE.value), inputs=[h_pid], outputs=[h_result])
    h_recover_btn.click(fn=_recover_all, outputs=[h_result])


def _build_console_tab():
    """构造 Console Tab（简化版，保留核心功能）"""
    import gradio as gr

    gr.Markdown("### ⚡ WebAuto 抢购控制台")

    gr.Markdown(
        "智谱 GLM Coding 抢购控制台完整版请访问：\n"
        "```\npython Tools/console.py\n```\n"
        "此 Tab 提供快捷入口和状态总览。"
    )

    with gr.Row():
        with gr.Column():
            gr.Markdown("""
**功能说明：**

- **Tab1 Console**：完整的抢购控制台，支持多账号、时间配置、实时状态
- **Tab2 智谱凭证**：管理 GLM 账号 token/cookie、短信登录
- **Tab3 Profile**：管理浏览器指纹账号（创建/编辑/删除/池化）
- **Tab4 Proxy**：管理代理池（健康追踪/批量导入）

**端口说明：**
| 端口 | 服务 |
|------|------|
| 7860 | 本面板（统一入口） |
| 7861 | console.py（完整控制台） |
| 7862 | profile_panel.py |
| 7863 | proxy_panel.py |
""")
        with gr.Column():
            gr.Markdown("""
**启动命令：**

```bash
# 统一面板（4 in 1）
python Tools/webauto_web.py

# 单独启动
python -m Tools.profile_panel  # 7862
python -m Tools.proxy_panel     # 7863
python Tools/console.py        # 7861
```

**Profile 池化流程：**

```
创建 Profile
    ↓
acquire 借出（自动选或指定 ID）
    ↓
浏览器使用 Profile
    ↓
release 归还（可设 cooldown 防风控）
```
""")


# ─── 主程序 ─────────────────────────────────────────────────────

def _build_ui():
    import gradio as gr

    with gr.Blocks(title="WebAuto 统一面板") as demo:
        gr.Markdown("# 🚀 WebAuto 统一管理面板")
        gr.Markdown("智谱抢购 · 凭证管理 · Profile 池 · Proxy 池，四合一入口")

        # Tab 1: Console
        with gr.Tab("⚡ Console"):
            _build_console_tab()

        # Tab 2: 智谱凭证
        with gr.Tab("🔐 智谱凭证"):
            _build_credential_tab()

        # Tab 3: Profile 管理
        with gr.Tab("🔑 Profile"):
            _build_profile_tab()

        # Tab 4: Proxy 管理
        with gr.Tab("🌐 Proxy"):
            _build_proxy_tab()

    return demo


def main():
    parser = argparse.ArgumentParser(description="WebAuto 统一管理面板")
    parser.add_argument("--port", type=int, default=7860, help="监听端口")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--share", action="store_true", help="生成 Gradio 分享链接")
    args = parser.parse_args()

    demo = _build_ui()
    print(f"🚀 启动 WebAuto 统一面板 → http://{args.host}:{args.port}")
    print(f"   4 Tab: Console | 智谱凭证 | Profile | Proxy")
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
    )


if __name__ == "__main__":
    main()
