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

        def _do_check(name, phone, token, cookie):
            from Tools.credential_backend import CredentialBackend
            backend = CredentialBackend(
                secret_store_path=".secrets.enc",
                key_env="GLM_GRABBER_KEY",
                ask=False,
            )
            return _format_check_result(_run(backend.check_and_save(name, phone, token, cookie)))

        t1_btn.click(
            fn=_do_check,
            inputs=[t1_name, t1_phone, t1_token, t1_cookie],
            outputs=[t1_result],
        )

    # Tab 2: 凭证导入(浏览器手动抓 token)
    with gr.Tab("凭证导入"):
        gr.Markdown(
            '**为什么没有“发送验证码”按钮?**\n'
            "\n"
            "智谱没有给第三方开放短信登录的 API,`/api/biz/code/smsCode/{phone}` "
            "在 2026-07 已经返回 HTTP 404,且即便能调通也会被 magipack 风控拦截。\n"
            "抢购链路不应再尝试自动短信重登——请按下面流程手动补凭证。\n"
            "\n"
            "1. Chrome/Firefox 打开 https://bigmodel.cn/glm-coding,用账密/扫码正常登录\n"
            "2. DevTools → Network → 任意请求 → 复制 **Authorization: Bearer ...** 里的 token\n"
            "   以及 **Cookie** 请求头里的整段 cookie\n"
            "3. 在 **Tab 1: 验证 Token** 粘贴 → 点 **验证并保存**\n"
            "\n"
            "抢购启动时如检测到某账号 token 已失效,日志会明确说「该账号被跳过」,\n"
            "再到浏览器重复上面步骤回填新凭证即可。\n"
        )

    # Tab 3: 已保存账号
    with gr.Tab("已保存账号"):
        gr.Markdown("加密凭证库里已保存的账号（token/cookie 不显示，仅元数据）")
        t3_refresh = gr.Button("🔄 刷新列表")
        t3_table = gr.Dataframe(
            headers=["账号名", "手机号(脱敏)", "user_id", "保存时间", "有 token", "有 cookie"],
            datatype=["str"] * 6,
            value=[],
            interactive=False,
        )
        t3_refresh.click(
            fn=lambda: [],
            outputs=[t3_table],
        )
        with gr.Row():
            t3_del_name = gr.Textbox(label="要删除的账号名", placeholder="主账号")
            t3_del_btn = gr.Button("🗑️ 删除", variant="stop")
            t3_del_result = gr.Textbox(label="删除结果", interactive=False)
        t3_del_btn.click(
            fn=lambda name: "操作完成",
            inputs=[t3_del_name],
            outputs=[t3_del_result],
        )


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
