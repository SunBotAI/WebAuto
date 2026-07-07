"""智谱凭证管理 Web 面板(Gradio).

启动:python Tools/credential_panel.py
浏览器:http://localhost:7860

提供三个能力:
  Tab 1: 粘贴 token/cookie → 验证 + 加密保存
  Tab 2: 短信登录(账密 + 短信码) → 自动 check + 保存
  Tab 3: 已保存账号管理(脱敏列表 + 删除)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 让 Tools/ 能 import 上层 Core/
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Tools.credential_backend import CredentialBackend
import gradio as gr  # 修复:main() 用到 gr.themes.Soft(),原代码只 build_ui 内 lazy import


def _run(coro):
    """同步跑 async 协程(Gradio callback 用)。"""
    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _check_passphrase(backend: CredentialBackend) -> str:
    """检查加密口令配置状态,UI 顶部提示。"""
    return backend.check_passphrase()["message"]


def _accounts_to_rows(accounts: list[dict]) -> list[list]:
    """list[dict] → list[list],适配 gr.Dataframe(value=...)。

    Gradio Dataframe 在 value= 参数接收 list[dict] 时会报 unhashable dict,
    改成 list[list] 最稳。
    """
    if not accounts:
        return [[]] * 6   # 6 列,空表格
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


def build_ui(backend: CredentialBackend):
    """构造 Gradio UI 并返回 demo 对象。"""
    import gradio as gr

    with gr.Blocks(title="WebAuto 智谱凭证管理") as demo:
        gr.Markdown(
            f"""
# 🛡️ WebAuto 智谱凭证管理

{_check_passphrase(backend)}

**用法**:
1. Tab 1:从浏览器 F12 → Network → 找 `getCustomerInfo` 请求,把 `Authorization` 头 / `Cookie` 粘进来
2. Tab 2:用手机号 + 短信码登录(适合 token 过期时刷新)
3. Tab 3:查看已保存的账号 + 删除

> 详细见 [README.md](../README.md) 智谱 AI GLM Coding 套餐抢购 章节
            """
        )

        # ============================ Tab 1: 粘贴 Token

        with gr.Tab("粘贴 Token / Cookie"):
            gr.Markdown("### 把浏览器 F12 抓的 Authorization / Cookie 粘进下面,点验证并保存")
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
                        label="Cookie (可选,从浏览器 Cookie 取)",
                        placeholder="atlas_t=xxx; _bl_uid=xxx; ...",
                        lines=4,
                    )
                    t1_btn = gr.Button("✅ 验证并保存", variant="primary")
                with gr.Column():
                    t1_result = gr.Textbox(
                        label="结果", interactive=False, lines=8,
                    )

            t1_btn.click(
                fn=lambda name, phone, token, cookie: _format_check_result(
                    _run(backend.check_and_save(name, phone, token, cookie))
                ),
                inputs=[t1_name, t1_phone, t1_token, t1_cookie],
                outputs=t1_result,
            )

        # ============================ Tab 2: 短信登录

        with gr.Tab("短信登录"):
            gr.Markdown(
                "### 📱 用智谱账密 + 短信验证码登录(最适合日常刷新 token)\n"
                "> **第一步**:填账号名 + 手机号,点\"发送验证码\",智谱会发 6 位短信到你手机\n"
                "> **第二步**:看到短信后填入验证码,点\"登录并保存\" → 自动调 API 校验 → 抓 token → 加密保存\n"
                "> 💡 **60 秒没收到短信就点\"重发验证码\"**"
            )
            with gr.Row():
                with gr.Column():
                    t2_name = gr.Textbox(label="账号名", value="主账号")
                    t2_phone = gr.Textbox(label="手机号", placeholder="138xxxxxxxx")
                    with gr.Row():
                        t2_send_btn = gr.Button("📤 发送验证码", variant="primary")
                        t2_resend_btn = gr.Button("🔁 重发验证码")
                    # SMS 状态区:点发送后才更新(给用户倒计时提示)
                    t2_sms_status = gr.Textbox(
                        label="短信状态",
                        value="(未发送)",
                        interactive=False,
                        lines=2,
                    )
                    # 验证码输入组
                    t2_code = gr.Textbox(
                        label="短信验证码(6 位数字)",
                        placeholder="短信里的 6 位数字",
                        max_lines=1,
                    )
                    t2_login_btn = gr.Button("✅ 登录并保存", variant="primary")
                with gr.Column():
                    t2_result = gr.Textbox(label="结果", interactive=False, lines=10)

            # 状态对象:跨按钮共享(发送成功后让验证码按钮变可用)
            sms_state = gr.State(value={"code_sent": False, "phone": "", "name": ""})

            def _do_send_code(name, phone, state):
                """发送验证码,更新 sms_state,返回 (status_text, sms_state)。"""
                if not phone.strip():
                    return "⚠️ 请先填写手机号", state
                result = _run(backend.login_by_sms(name, phone))
                # 发送成功 → 把 code_sent 置 True
                new_state = dict(state)
                new_state["code_sent"] = result.get("stage") == "code_sent"
                new_state["phone"] = phone
                new_state["name"] = name
                return _format_sms_result(result), new_state

            def _do_login(name, phone, code, state):
                """校验验证码,登录保存。"""
                if not code.strip():
                    return "⚠️ 请先填写 6 位短信验证码", state
                if not phone.strip():
                    return "⚠️ 手机号不能为空", state
                # 如果用户改了手机号,提示重新发送
                if state.get("phone") and state["phone"] != phone:
                    return (
                        f"⚠️ 你改了手机号({state.get('phone')} → {phone}),"
                        f"需要重新点 [发送验证码]",
                        state,
                    )
                result = _run(
                    backend.login_by_sms(name, phone, sms_code=code)
                )
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
                fn=_do_send_code,  # 重发和首次发送逻辑相同
                inputs=[t2_name, t2_phone, sms_state],
                outputs=[t2_sms_status, sms_state],
            )
            t2_login_btn.click(
                fn=_do_login,
                inputs=[t2_name, t2_phone, t2_code, sms_state],
                outputs=[t2_result, sms_state],
            )

        # ============================ Tab 3: 已保存账号管理

        with gr.Tab("已保存账号"):
            gr.Markdown("### 加密凭证库里已保存的账号(token/cookie 不显示,仅元数据)")
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
                fn=lambda name: _run(backend.delete_account(name)).get(
                    "message", "操作完成"
                ),
                inputs=t3_del_name,
                outputs=t3_del_result,
            )

        # ============================ Tab 4: 扫码登录(自动)

        with gr.Tab("扫码登录(自动)"):
            gr.Markdown(
                "### Playwright 自动扫码登录\n"
                "> 点启动 → 自动开浏览器 + 打开 bigmodel.cn 登录页 + 截图二维码\n"
                "> **用智谱 App 扫描屏幕上的二维码**,登录完成后自动保存"
            )
            with gr.Row():
                with gr.Column():
                    t4_name = gr.Textbox(label="账号名", value="主账号")
                    t4_phone = gr.Textbox(
                        label="手机号(可选,仅记录)",
                        placeholder="138xxxxxxxx",
                    )
                    t4_btn = gr.Button("🚀 启动扫码登录", variant="primary")
                with gr.Column():
                    t4_status = gr.Textbox(
                        label="状态", interactive=False, lines=4, value="(等待点击启动)",
                    )
                    t4_qrcode = gr.Image(
                        label="二维码(请用智谱 App 扫描)",
                        height=320,
                        type="filepath",
                    )

            # 异步执行:启动后台线程跑 asyncio 流程
            t4_btn.click(
                fn=lambda name, phone: _start_scan_login(backend, name, phone),
                inputs=[t4_name, t4_phone],
                outputs=[t4_status, t4_qrcode],
            )

    return demo


# ============================================================
# Tab 4 扫码登录:gradio 同步 ↔ asyncio 异步的桥接
# ============================================================

import threading


def _start_scan_login(
    backend: CredentialBackend,
    account_name: str,
    phone: str,
    timeout_budget: int = 140,  # 比 Playwright 的 120s 超时多给点 buffer
) -> tuple[str, Optional[str]]:
    """启动扫码登录(在后台线程跑 asyncio,不阻塞 gradio UI)。

    Returns:
        (status_text, qrcode_image_path)
        qrcode_image_path: PNG 文件路径,gradio.Image 自动渲染
    """
    import base64
    import tempfile
    from datetime import datetime

    result_holder: dict[str, Any] = {}

    def run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 进度回调容器
            latest_progress = {"qrcode_b64": "", "message": ""}

            def on_progress(progress):
                latest_progress["qrcode_b64"] = progress.qrcode_b64
                latest_progress["message"] = progress.message
                # 实时落盘二维码图片,gradio 可以 polling 它
                if progress.qrcode_b64 and progress.stage != "init":
                    try:
                        out = Path(tempfile.gettempdir()) / "webauto_qrcode.png"
                        out.write_bytes(base64.b64decode(progress.qrcode_b64))
                        latest_progress["qrcode_b64_path"] = str(out)
                    except Exception:
                        pass

            result = loop.run_until_complete(
                backend.auto_login_and_save(
                    account_name=account_name,
                    phone=phone,
                    timeout_sec=120,
                    progress_callback=on_progress,
                )
            )
            result_holder["result"] = result
            result_holder["qrcode_path"] = latest_progress.get("qrcode_b64_path", "")
        finally:
            loop.close()

    t = threading.Thread(target=run_in_thread, daemon=True)
    t.start()
    t.join(timeout=timeout_budget)

    if t.is_alive():
        return (
            f"⏰ 超过 {timeout_budget}s 仍卡住,可能 playwright 启动失败。\n"
            f"检查终端是否有 [playwright] 错误。",
            None,
        )

    result = result_holder.get("result", {})
    status_text = _format_scan_login_result(result)
    qrcode_path = result_holder.get("qrcode_path") or None
    return status_text, qrcode_path


def _format_scan_login_result(result: dict) -> str:
    """格式化扫码登录结果给 UI 显示。"""
    stage = result.get("stage", "")
    success = result.get("success", False)
    if success:
        return (
            f"✅ {result.get('message', '扫码登录成功')}\n"
            f"   user_id: {result.get('user_id', '?')}\n"
            f"   凭证已加密保存"
        )
    return f"❌ {result.get('message', '扫码登录失败')}"


def _format_check_result(result: dict) -> str:
    """把 check_and_save 的 dict 格式化成多行文本给 UI 显示。"""
    lines = []
    success = "✅ 成功" if result.get("success") else "❌ 失败"
    lines.append(success)
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
    """把 login_by_sms 的 dict 格式化成多行文本。"""
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


def main():
    parser = argparse.ArgumentParser(description="WebAuto 智谱凭证管理面板")
    parser.add_argument("--port", type=int, default=7860, help="监听端口")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址(远程访问改成 0.0.0.0)")
    parser.add_argument(
        "--share", action="store_true",
        help="生成 Gradio 公开分享链接(72h 有效,仅调试用)",
    )
    parser.add_argument(
        "--store-path", default=".secrets.enc", help="加密凭证库路径",
    )
    parser.add_argument(
        "--key-env", default="GLM_GRABBER_KEY", help="加密口令环境变量名",
    )
    args = parser.parse_args()

    backend = CredentialBackend(
        secret_store_path=args.store_path,
        key_env=args.key_env,
        ask=False,
    )

    demo = build_ui(backend)
    print(f"🚀 启动 Gradio 面板 → http://{args.host}:{args.port}")
    print(f"   凭证库: {args.store_path}")
    print(f"   加密口令: {args.key_env} {'(已设置)' if backend.check_passphrase()['configured'] else '(未设置,UI 顶部会有提示)'}")
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        theme=gr.themes.Soft(),
    )


if __name__ == "__main__":
    main()