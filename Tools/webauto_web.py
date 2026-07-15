"""WebAuto 统一 Web 面板 (Gradio).

启动: python Tools/webauto_web.py
端口: 7860 (--port 可改)

四个 Tab:
  Tab1: Console（抢购控制台）
  Tab2: 智谱凭证（credential_panel）
  Tab3: Profile 管理（profile_panel_tab.py）
  Tab4: Proxy 管理（proxy_panel_tab.py）

Profile/Proxy Tab 实现来自独立的 *_tab.py 文件，
保证 profile_panel.py / proxy_panel.py 单独启动时功能完整。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ─── Tab 实现（独立文件）──────────────────────────────

from Tools.profile_tab import build_profile_tab
from Tools.proxy_panel_tab import build_proxy_tab
from Tools.console_tab import build_console_tab


# ─── 凭证 Tab（inline，避免顶层 import 链冲突）─────────────

def _build_credential_tab():
    """构造凭证管理 Tab（从 credential_panel.py 的 UI 逻辑重构）"""
    import asyncio
    import gradio as gr

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

    # ── Tab 1: 手动填凭证（Token/Cookie）────────────────────────
    with gr.Tab("🔑 手动填凭证(Token/Cookie)"):
        gr.Markdown(
            "把浏览器 F12 抓的 Authorization / Cookie 粘进下面，点验证并保存。\n"
            "验证通过后自动落加密凭证库（Fernet 加密），**不存明文**。"
        )

        # 基本信息
        with gr.Group():
            t1_name = gr.Textbox(
                label="账号名",
                placeholder="主账号",
                value="主账号",
                info="本地标识名，方便在 Console 里区分账号",
            )
            t1_phone = gr.Textbox(
                label="手机号",
                placeholder="138xxxxxxxx",
                info="用于智谱登录的手机号",
            )

        # 凭证区（折叠起来避免视觉干扰）
        with gr.Accordion("🔐 Token / Cookie（点展开）", open=True):
            with gr.Group():
                t1_token = gr.Textbox(
                    label="Bearer Token",
                    placeholder="eyJhbGciOiJIUzI1NiIs...",
                    type="password",
                    info="从浏览器 F12 → Network → Authorization 头复制，格式为 'Bearer xxx'",
                )
                t1_cookie = gr.Textbox(
                    label="Cookie（可选）",
                    placeholder="atlas_t=xxx; _bl_uid=xxx; ...",
                    lines=3,
                    info="从 F12 → Network → 请求头复制 Cookie 字段",
                )

        # 操作按钮
        with gr.Group():
            with gr.Row():
                t1_test_btn = gr.Button("🔍 测试连接", variant="secondary")
                t1_save_btn = gr.Button("✅ 验证并保存", variant="primary")

            test_result = gr.Textbox(label="测试结果", interactive=False, lines=2)
            save_result = gr.Textbox(label="保存结果", interactive=False, lines=3)

        def _do_test(name, phone, token, cookie):
            from Tools.credential_backend import CredentialBackend
            backend = CredentialBackend(ask=False)
            result = _run(backend.check_and_save(name, phone, token, cookie))
            lines = []
            if result.get("success"):
                lines.append(f"✅ Token 有效（user_id: {result.get('user_id', '?')}）")
            else:
                err = result.get("message", "未知错误")
                if "验证失败" in err or "401" in err or "token invalid" in err.lower():
                    lines.append(f"❌ Token/Cookie 无效：{err}")
                elif "网络" in err:
                    lines.append(f"❌ 网络错误：{err}")
                elif "授权" in err or "403" in err:
                    lines.append(f"❌ 授权失败（403）：{err}")
                else:
                    lines.append(f"❌ 验证失败：{err}")
            return "\n".join(lines)

        def _do_save(name, phone, token, cookie):
            from Tools.credential_backend import CredentialBackend
            backend = CredentialBackend(ask=False)
            result = _run(backend.check_and_save(name, phone, token, cookie))
            return _format_check_result(result)

        t1_test_btn.click(
            fn=_do_test,
            inputs=[t1_name, t1_phone, t1_token, t1_cookie],
            outputs=[test_result],
        )
        t1_save_btn.click(
            fn=_do_save,
            inputs=[t1_name, t1_phone, t1_token, t1_cookie],
            outputs=[save_result],
        )

    # ── Tab 2: 手机号+短信码登录(自动)────────────────────────
    with gr.Tab("📱 手机号登录(自动)"):
        gr.Markdown(
            "**流程: 启动登录 → 浏览器自动打开智谱首页 → 点登录 → 输手机号 → 触发腾讯点选**\n"
            "**你在浏览器里用鼠标点汉字 → 等短信 → 面板填 6 位码 → 自动登录 → 落加密库**\n\n"
            "面板上的「验证码截图」仅供你确认是哪张图；汉字必须用鼠标在浏览器里点。\n"
            "（弹窗是浏览器层面的，Playwright 控制不了鼠标语义）。"
        )
        _t2_state: dict = {"task": None, "sms_future": None, "running": False}

        with gr.Row():
            with gr.Column():
                t2_name = gr.Textbox(label="账号名", placeholder="主账号")
                t2_phone = gr.Textbox(label="手机号(国内 11 位)", placeholder="138xxxxxxxx")
                with gr.Row():
                    t2_start = gr.Button("🚀 启动登录", variant="primary")
                    t2_cancel = gr.Button("🛑 取消", variant="stop")
                t2_stage = gr.Textbox(label="阶段", value="(未开始)", interactive=False)
            with gr.Column():
                t2_captcha = gr.Image(label="腾讯点选验证(浏览器里点)", height=200)
                t2_sms = gr.Textbox(label="短信 6 位码", max_lines=1,
                                     placeholder="短信里的 6 位数字")
                t2_submit = gr.Button("📨 提交短信码", variant="primary")
                t2_status = gr.Textbox(label="状态", value="", interactive=False, lines=6)

        def _t2_start(name, phone):
            if _t2_state["running"]:
                return ("已在运行中", None, "⚠️ 已有一个登录任务在跑")
            if not name.strip():
                return ("(未开始)", None, "⚠️ 账号名必填")
            if not phone or len(phone) < 11:
                return ("(未开始)", None, "⚠️ 手机号格式错(11 位)")

            from Tools.credential_backend import CredentialBackend
            backend = CredentialBackend(ask=False)
            progress_log: list[str] = []
            captcha_b64_holder: list[str] = [""]

            def _cb(p):
                progress_log.append(f"📡 {p.stage}: {p.message}")
                if p.captcha_b64:
                    captcha_b64_holder[0] = p.captcha_b64

            import asyncio as _aio
            try:
                loop = _aio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError
            except RuntimeError:
                loop = _aio.new_event_loop()
                _aio.set_event_loop(loop)

            sms_future = loop.create_future()
            async def _wrap_provider() -> str:
                return await sms_future

            async def _go():
                return await backend.phone_login_and_save(
                    account_name=name,
                    phone=phone,
                    sms_code_provider=_wrap_provider,
                    timeout_sec=180,
                    progress_callback=_cb,
                )
            task = loop.create_task(_go())
            _t2_state["task"] = task
            _t2_state["sms_future"] = sms_future
            _t2_state["running"] = True

            import time
            for _ in range(20):
                time.sleep(0.3)
                if captcha_b64_holder[0] or task.done():
                    break

            img = None
            if captcha_b64_holder[0]:
                import base64, io
                try:
                    from PIL import Image
                    img = Image.open(io.BytesIO(base64.b64decode(captcha_b64_holder[0])))
                except Exception:
                    img = None
            summary = "\n".join(progress_log[-8:]) if progress_log else "启动中..."
            return (progress_log[-1] if progress_log else "init", img, summary)

        def _t2_submit_sms(code):
            fut = _t2_state.get("sms_future")
            if fut is None or fut.done():
                return "⚠️ 没有等待中的登录任务(可能已超时/取消)"
            if not code or len(code.strip()) < 4:
                return "⚠️ 短信码至少 4 位"
            fut.get_loop().call_soon_threadsafe(fut.set_result, code.strip())
            return "✅ 短信码已提交,等待登录..."

        def _t2_cancel():
            fut = _t2_state.get("sms_future")
            task = _t2_state.get("task")
            if fut is not None and not fut.done():
                fut.get_loop().call_soon_threadsafe(fut.set_result, "")
            if task is not None and not task.done():
                task.cancel()
            _t2_state["running"] = False
            return "已取消"

        def _t2_poll():
            task = _t2_state.get("task")
            if task is None:
                return ("(未开始)", "未启动登录")
            if task.done():
                try:
                    r = task.result()
                except Exception as e:
                    _t2_state["running"] = False
                    return ("error", f"异常: {e}")
                _t2_state["running"] = False
                if r.get("success"):
                    return ("done", f"✅ 登录成功 → {r.get('message', '')}\nuser_id: {r.get('user_id', '')}")
                return ("failed", f"❌ {r.get('message', r.get('stage', 'failed'))}")
            return ("waiting", "流程进行中... 等待:浏览器点汉字 + 面板填 6 位码")

        t2_start.click(fn=_t2_start, inputs=[t2_name, t2_phone],
                       outputs=[t2_stage, t2_captcha, t2_status])
        t2_submit.click(fn=_t2_submit_sms, inputs=[t2_sms], outputs=[t2_status])
        t2_cancel.click(fn=_t2_cancel, outputs=[t2_status])
        _t2_timer = gr.Timer(value=3)
        _t2_timer.tick(fn=_t2_poll, outputs=[t2_stage, t2_status])

    # ── Tab 3: 已保存账号───────────────────────────────────────
    with gr.Tab("📋 已保存账号"):
        gr.Markdown("加密凭证库里已保存的账号（token/cookie 不显示，仅元数据）")
        t3_refresh = gr.Button("🔄 刷新列表")
        t3_table = gr.Dataframe(
            headers=["账号名", "手机号(脱敏)", "user_id", "保存时间", "有 token", "有 cookie"],
            datatype=["str"] * 6,
            value=[],
            interactive=False,
        )

        def _t3_list_rows():
            try:
                from Tools.credential_backend import CredentialBackend
                backend = CredentialBackend(ask=False)
                accounts = _run(backend.list_accounts())
                rows = []
                for a in accounts:
                    rows.append([
                        a.get("name", ""),
                        a.get("phone", ""),
                        a.get("user_id", ""),
                        a.get("saved_at", ""),
                        "✅" if a.get("has_token") else "—",
                        "✅" if a.get("has_cookie") else "—",
                    ])
                return rows
            except Exception as e:
                return [[f"(读取失败: {e})", "", "", "", "", ""]]

        def _t3_delete(name):
            if not name.strip():
                return "⚠️ 请填写要删除的账号名"
            try:
                from Tools.credential_backend import CredentialBackend
                backend = CredentialBackend(ask=False)
                result = _run(backend.delete_account(name.strip()))
                if result.get("success"):
                    return "✅ " + result.get("message", "")
                return "❌ " + result.get("message", "失败")
            except Exception as e:
                return f"❌ 异常: {e}"

        t3_refresh.click(fn=_t3_list_rows, outputs=[t3_table])
        # 初始值:Tab 打开时刷一次
        t3_table.value = _t3_list_rows()

        with gr.Row():
            t3_del_name = gr.Textbox(label="要删除的账号名", placeholder="主账号")
            t3_del_btn = gr.Button("🗑️ 删除", variant="stop")
            t3_del_result = gr.Textbox(label="删除结果", interactive=False)
        # 删除后顺手刷新一次表格
        t3_del_btn.click(
            fn=_t3_delete, inputs=[t3_del_name], outputs=[t3_del_result]
        ).then(fn=_t3_list_rows, outputs=[t3_table])


# ─── 主程序 ─────────────────────────────────────────────────────

def _build_ui():
    import gradio as gr

    with gr.Blocks(title="WebAuto 统一面板") as demo:
        gr.Markdown("# 🚀 WebAuto 统一管理面板")
        gr.Markdown("智谱抢购 · 凭证管理 · Profile 池 · Proxy 池，四合一入口")

        # Tab 1: Console（完整版来自 console_tab.py）
        with gr.Tab("⚡ Console"):
            build_console_tab()

        # Tab 2: 智谱凭证
        with gr.Tab("🔐 智谱凭证"):
            _build_credential_tab()

        # Tab 3: Profile 管理（来自 profile_tab.py）
        with gr.Tab("🔑 Profile"):
            build_profile_tab()

        # Tab 4: Proxy 管理（来自 proxy_panel_tab.py）
        with gr.Tab("🌐 Proxy"):
            build_proxy_tab()

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
        server_port=args.port,
        share=args.share,
    )


if __name__ == "__main__":
    main()
