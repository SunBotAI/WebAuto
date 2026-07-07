"""智谱 GLM Coding 抢购控制台.

单页面 gradio 应用:
- 左侧:套餐 + 时间参数 + 多账号动态管理
- 右侧:实时多账号抢单状态表格
- 底部:实时日志

启动:python Tools/console.py
浏览器:http://localhost:7860(默认,与 credential_panel 端口冲突时自动 7861)

完全复用 Core/Zhipu/* 和 Tools/credential_backend,只做编排和展示。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import queue
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Tools.console_backend import (
    AccountProgress,
    ConsoleState,
    add_account,
    add_plan_group,
    make_plan_group_rows,
    make_progress_rows,
    make_summary,
    remove_account,
    remove_plan_group,
    resolve_target_ts,
    state_to_appconfig_kwargs,
    toggle_plan_group,
)


def _format_sms_result(result: dict) -> str:
    """把 login_by_sms 的 dict 格式化成多行文本(给 UI 显示)。

    复用 credential_panel.py 的格式约定,保持一致体验。
    """
    stage = result.get("stage", "?")
    success = result.get("success")
    msg = result.get("message", "")
    lines = [f"📡 阶段: {stage}", f"📝 {msg}"]
    if "user_id" in result:
        if result.get("user_id"):
            lines.append(f"👤 user_id: {result['user_id']}")
        if result.get("customer_number"):
            lines.append(f"🔢 customer_number: {result['customer_number']}")
        if result.get("expires_hint"):
            lines.append(f"⏰ {result['expires_hint']}")
    lines.append(f"{'✅ 成功' if success else '❌ 失败' if success is False else ''}".strip())
    return "\n".join(lines)


def _run(coro):
    """同步跑 async。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _format_log_line(line: str) -> str:
    """给日志加时间戳。"""
    ts = datetime.now().strftime("%H:%M:%S")
    return f"[{ts}] {line}"


def build_console_ui():
    """构造 gradio 控制台 UI 并返回 demo。"""
    import gradio as gr

    initial_state = ConsoleState()
    initial_state = add_account(initial_state)  # 默认一个账号
    # 默认给 1 个套餐配置组,沿用单套餐 UI 的初值(Max/年/支付宝)
    initial_state = add_plan_group(
        initial_state,
        name="默认",
        target_plan="Max",
        billing_cycle="yearly",
        pay_channel="alipay",
    )

    with gr.Blocks(title="WebAuto 智谱抢购控制台") as demo:
        gr.Markdown(
            "# 🛡️ WebAuto 智谱 GLM Coding 抢购控制台\n"
            "所有参数在页面配置,不用改 yaml。点 [🔥 开始抢] 后等倒计时到点自动下单。"
        )

# ============================ 顶部:账号登录(SMS 验证码) ============================
        # 独立登录区:点 🔥 开始抢前用这里登录。
        # 复用 CredentialBackend.login_by_sms() 的两阶段流程。
        # 成功后 token 进 .secrets.enc;账号 token 可用后自动加到抢单账号列表里(见回调)。
        with gr.Accordion("📱 账号登录(SMS 验证码)- 不登录也能抢,但账号必须有 token", open=False):
            from Tools.credential_backend import CredentialBackend

            _cred_backend = CredentialBackend()

            with gr.Row():
                with gr.Column(scale=1):
                    login_name = gr.Textbox(
                        label="账号名",
                        placeholder="主账号(用于在抢单账号列表里识别)",
                    )
                    login_phone = gr.Textbox(
                        label="手机号",
                        placeholder="138xxxxxxxx",
                    )
                    login_send_btn = gr.Button(
                        "📤 发送验证码", variant="primary",
                    )
                with gr.Column(scale=1):
                    login_code = gr.Textbox(
                        label="短信验证码(6 位)",
                        placeholder="收到的 6 位数字",
                        max_lines=1,
                    )
                    login_submit_btn = gr.Button(
                        "✅ 登录并保存", variant="primary",
                    )
                    login_status = gr.Textbox(
                        label="登录状态",
                        value="(未发送)",
                        interactive=False,
                        lines=4,
                    )

            # 跨按钮共享:发送成功后,submit 按钮读 sms_code
            sms_state = gr.State(value={"code_sent": False, "name": "", "phone": ""})
            # 模块级 bridge:把登录成功的账号追加到 state.accounts,
            # 等到用户后续点 [开始抢] 时 ConsoleState 已被更新。
            # gradio 的 State 是 build 时创建的,这里先放个占位,build 后再 inject。
            _accounts_bridge: dict[str, Any] = {"state": None}

            def _do_send_code(name, phone, state):
                if not phone.strip():
                    return "⚠️ 请先填写手机号", state
                if not name.strip():
                    return "⚠️ 请先填写账号名", state
                result = _run(_cred_backend.login_by_sms(name, phone))
                new_state = dict(state)
                new_state["code_sent"] = result.get("stage") == "code_sent"
                new_state["phone"] = phone
                new_state["name"] = name
                return _format_sms_result(result), new_state

            def _do_login(name, phone, code, state):
                if not code.strip():
                    return "⚠️ 请先填写 6 位短信验证码", state
                result = _run(_cred_backend.login_by_sms(name, phone, sms_code=code))
                msg = _format_sms_result(result)
                # 登录成功:把账号追加到 bridge 里的 state
                if result.get("stage") == "done" and result.get("success"):
                    bridge = _accounts_bridge
                    current = bridge["state"]
                    if current is not None:
                        new_state = add_account(
                            current,
                            name=name.strip(),
                            phone=phone.strip(),
                        )
                        bridge["state"] = new_state
                return msg, state

            login_send_btn.click(
                fn=_do_send_code,
                inputs=[login_name, login_phone, sms_state],
                outputs=[login_status, sms_state],
            )
            login_submit_btn.click(
                fn=_do_login,
                inputs=[login_name, login_phone, login_code, sms_state],
                outputs=[login_status, sms_state],
            )

        # ============================ 套餐配置(多组)
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 🎯 套餐配置(多组 · 并行)")
                gr.Markdown(
                    "每组是一组独立的抢购配置(目标套餐/周期/支付),"
                    "点 [开始抢] 后所有 enabled 组并发执行,共享 NTP + 账号 token。"
                )
                plan_group_table = gr.Dataframe(
                    headers=["组名", "套餐", "周期", "支付", "拼好模", "降级", "启用", "备注"],
                    datatype=["str", "str", "str", "str", "str", "str", "str", "str"],
                    value=make_plan_group_rows(initial_state),
                    interactive=False,
                )
                with gr.Row():
                    new_group_name = gr.Textbox(label="组名", placeholder="(留空自动编号)", scale=2)
                    new_group_plan = gr.Dropdown(
                        choices=["Max", "Pro", "Lite"],
                        value="Max", label="目标套餐", scale=2,
                    )
                    new_group_cycle = gr.Dropdown(
                        choices=["yearly", "quarterly", "monthly"],
                        value="yearly", label="周期", scale=2,
                    )
                    new_group_channel = gr.Dropdown(
                        choices=["alipay", "weChat_pay", "balance_pay"],
                        value="alipay", label="支付", scale=2,
                    )
                with gr.Row():
                    new_group_fallback = gr.Textbox(
                        label="组内降级顺序",
                        placeholder="Pro,Lite(逗号分隔,留空=不降级)",
                        scale=4,
                    )
                    add_group_btn = gr.Button("➕ 添加组", variant="primary", scale=1)
                with gr.Row():
                    del_group_name = gr.Textbox(label="要删除的组名", scale=3)
                    del_group_btn = gr.Button("🗑 删除组", variant="stop", scale=1)
                    toggle_group_name = gr.Textbox(label="切换启用状态的组名", scale=3)
                    toggle_group_btn = gr.Button("🔁 切换启用", scale=1)

        # ============================ 左:参数 + 账号
        with gr.Row():
            with gr.Column(scale=2):
                gr.Markdown("### ⚙️ 单套餐视图(留空则被多组配置覆盖)")
                plan = gr.Dropdown(
                    choices=["Max", "Pro", "Lite"],
                    value="Max", label="目标套餐(legacy)",
                )
                cycle = gr.Dropdown(
                    choices=["yearly", "quarterly", "monthly"],
                    value="yearly", label="计费周期(legacy)",
                )
                downgrade = gr.Checkbox(
                    value=True, label="降级:失败自动试下一档(Max → Pro → Lite,legacy)",
                )
                gr.Markdown("---")
                time_mode = gr.Radio(
                    choices=[("⏱ 倒计时", "countdown"), ("📅 绝对时间", "absolute")],
                    value="countdown", label="开抢时间模式",
                )
                with gr.Row():
                    countdown_sec = gr.Number(
                        value=60, label="倒计时秒数", minimum=5, maximum=3600,
                        visible=True,
                    )
                    absolute_time = gr.Textbox(
                        label="绝对时间(YYYY-MM-DD HH:MM:SS)",
                        value="",
                        placeholder="2026-07-15 10:00:00",
                        visible=False,
                    )
                gr.Markdown("---")
                pay_channel = gr.Dropdown(
                    choices=["alipay", "weChat_pay", "balance_pay"],
                    value="alipay", label="支付方式",
                )
                max_concurrent = gr.Slider(
                    minimum=1, maximum=10, value=4, step=1, label="并发账号数",
                )
                with gr.Accordion("⚙️ 高级(进阶)", open=False):
                    burst_count = gr.Slider(
                        minimum=1, maximum=50, value=20, step=1,
                        label="零延迟爆发次数(前 N 次争首批)",
                    )
                    quick_count = gr.Slider(
                        minimum=1, maximum=30, value=10, step=1,
                        label="快速重试次数",
                    )
                    preheat_seconds = gr.Slider(
                        minimum=1, maximum=30, value=5, step=1,
                        label="预热连接秒数",
                    )

            with gr.Column(scale=3):
                gr.Markdown("### 👥 账号(动态添加)")
                account_table = gr.Dataframe(
                    headers=["账号名", "手机号", "已启用", "有 token"],
                    datatype=["str", "str", "bool", "bool"],
                    value=_accounts_table_value(initial_state),
                    interactive=False,
                )
                with gr.Row():
                    new_name = gr.Textbox(label="账号名", placeholder="主账号", scale=2)
                    new_phone = gr.Textbox(label="手机号", placeholder="138xxxxxxxx", scale=3)
                    add_btn = gr.Button("➕ 添加", scale=1)
                with gr.Row():
                    del_name = gr.Textbox(label="要删除的账号名", scale=3)
                    del_btn = gr.Button("🗑 删除", scale=1, variant="stop")
                gr.Markdown(
                    "💡 token 状态从 .secrets.enc 自动读取。"
                    "没有 token 的账号会被跳过,先在凭证管理面板登录。"
                )

        # ============================ 中:抢单状态
        gr.Markdown("### 🔥 抢单状态")
        with gr.Row():
            top_summary = gr.Textbox(
                label="汇总", value="(未开始)", interactive=False,
            )
            countdown_display = gr.Textbox(
                label="倒计时 / 状态", value="-", interactive=False,
            )
        with gr.Row():
            start_btn = gr.Button("🔥 开始抢", variant="primary", scale=2)
            cancel_btn = gr.Button("⏹ 取消", variant="stop", scale=1)
            dryrun_btn = gr.Button("🧪 模拟抢(不真下单)", scale=1)

        progress_table = gr.Dataframe(
            headers=["账号", "状态", "订单/bizId", "详情"],
            datatype=["str", "str", "str", "str"],
            value=make_progress_rows({}),
            interactive=False,
            row_count=(0, "dynamic"),
        )

        # ============================ 底部:日志
        gr.Markdown("### 📜 实时日志")
        log_box = gr.Textbox(
            value="", interactive=False, lines=10, max_lines=30,
            autoscroll=True,
        )

        # ============================ 状态对象
        state = gr.State(value=initial_state)
        # 把 initial_state 注进 _accounts_bridge,登录成功的账号追加到这里
        _accounts_bridge["state"] = initial_state
        # progress_queue 不能进 gr.State(不能 deepcopy)
        # 改用全局 dict 持有 active job,key=job_id
        from Tools.console_backend import ACTIVE_JOBS
        ACTIVE_JOBS.clear()

        # 时间模式切换
        def on_time_mode_change(mode):
            return gr.update(visible=(mode == "countdown")), gr.update(visible=(mode == "absolute"))

        time_mode.change(
            fn=on_time_mode_change,
            inputs=time_mode,
            outputs=[countdown_sec, absolute_time],
        )

        # 添加账号
        def on_add(state_val, name, phone):
            new_state = add_account(state_val, name=name, phone=phone)
            return new_state, _accounts_table_value(new_state)

        add_btn.click(
            fn=on_add,
            inputs=[state, new_name, new_phone],
            outputs=[state, account_table],
        )

        # 删除账号
        def on_delete(state_val, name):
            new_state = remove_account(state_val, name)
            return new_state, _accounts_table_value(new_state)

        del_btn.click(
            fn=on_delete,
            inputs=[state, del_name],
            outputs=[state, account_table],
        )

        # 添加套餐配置组
        def on_add_group(state_val, name, plan_v, cycle_v, channel_v, fallback_str):
            fallback_list = [
                x.strip() for x in (fallback_str or "").split(",") if x.strip()
            ]
            new_state = add_plan_group(
                state_val,
                name=name,
                target_plan=plan_v,
                billing_cycle=cycle_v,
                pay_channel=channel_v,
                fallback_within_group=fallback_list,
            )
            return new_state, make_plan_group_rows(new_state)

        add_group_btn.click(
            fn=on_add_group,
            inputs=[state, new_group_name, new_group_plan, new_group_cycle, new_group_channel, new_group_fallback],
            outputs=[state, plan_group_table],
        )

        # 删除套餐配置组
        def on_del_group(state_val, name):
            new_state = remove_plan_group(state_val, name)
            return new_state, make_plan_group_rows(new_state)

        del_group_btn.click(
            fn=on_del_group,
            inputs=[state, del_group_name],
            outputs=[state, plan_group_table],
        )

        # 切换套餐组启用
        def on_toggle_group(state_val, name):
            new_state = toggle_plan_group(state_val, name)
            return new_state, make_plan_group_rows(new_state)

        toggle_group_btn.click(
            fn=on_toggle_group,
            inputs=[state, toggle_group_name],
            outputs=[state, plan_group_table],
        )

        # ============================ 开始抢(后台线程)
        # active_job 不放 State(不能 deepcopy),改用 console_backend.ACTIVE_JOBS

        def _start_job(state_val, dry_run):
            """点击 [开始抢] / [模拟抢] 时启动后台线程。"""
            if state_val.running:
                return (
                    state_val,
                    gr.update(value="⚠ 已有抢单任务在运行,请先取消"),
                    gr.update(value="-"),
                    gr.update(),
                )

            if not state_val.accounts:
                return (
                    state_val,
                    gr.update(value="⚠ 请先添加账号"),
                    gr.update(value="-"),
                    gr.update(),
                )

            # 启动后台线程
            from Tools.console_backend import ConsoleJob, run_console_job, ACTIVE_JOBS
            import uuid
            stop_event = threading.Event()
            progress_q = queue.Queue()
            job_id = uuid.uuid4().hex[:8]
            ACTIVE_JOBS[job_id] = (stop_event, progress_q)

            job = ConsoleJob(
                state=state_val,
                progress_queue=progress_q,
                stop_event=stop_event,
                time_sync_factory=None,
            )

            def _run_in_thread():
                run_console_job(job)
                # 跑完从 ACTIVE_JOBS 移除
                ACTIVE_JOBS.pop(job_id, None)

            t = threading.Thread(target=_run_in_thread, daemon=True)
            t.start()

            # 更新 state
            new_state = ConsoleState(**asdict(state_val))
            new_state.running = True
            new_state.started_at = time.time()
            new_state.target_server_ts = resolve_target_ts(new_state)
            new_state.progress = {}
            new_state.logs = []
            new_state.final_summary = ""

            return (
                new_state,
                gr.update(value=f"⏰ 目标时间: {datetime.fromtimestamp(new_state.target_server_ts).strftime('%H:%M:%S')}"),
                gr.update(value=f"⏳ 准备中... (job_id={job_id})"),
                gr.update(),
            )

        start_btn.click(
            fn=_start_job,
            inputs=[state, gr.State(value=False)],
            outputs=[state, top_summary, countdown_display, gr.State()],
        )

        dryrun_btn.click(
            fn=_start_job,
            inputs=[state, gr.State(value=True)],
            outputs=[state, top_summary, countdown_display, gr.State()],
        )

        # ============================ 取消抢单
        def on_cancel(state_val):
            """点取消时设置所有 active job 的 stop_event。"""
            from Tools.console_backend import ACTIVE_JOBS
            count = 0
            for stop_event, _ in ACTIVE_JOBS.values():
                if not stop_event.is_set():
                    stop_event.set()
                    count += 1
            return state_val, f"已请求取消 {count} 个任务"

        cancel_btn.click(
            fn=on_cancel,
            inputs=[state],
            outputs=[state, top_summary],
        )

        # ============================ Timer 轮询:每秒更新进度 + 倒计时
        timer = gr.Timer(value=1.0, active=True)

        def on_timer_tick(state_val):
            """每秒触发:从 active job 的 queue 拉进度 + 更新倒计时。"""
            from Tools.console_backend import ACTIVE_JOBS

            new_state = ConsoleState(**asdict(state_val))
            logs = list(new_state.logs)
            updated = False

            # 0. 拉取 bridge 里的账号追加(短信登录成功的)
            bridge = _accounts_bridge.get("state")
            if bridge is not None and len(bridge.accounts) > len(new_state.accounts):
                new_state = ConsoleState(**asdict(bridge))
                updated = True

            # 1. 从所有 active job 的 queue 拉消息
            for stop_event, q in list(ACTIVE_JOBS.values()):
                while True:
                    try:
                        msg = q.get_nowait()
                    except queue.Empty:
                        break
                    msg_type = msg.get("type")
                    if msg_type == "log":
                        logs.append(_format_log_line(msg["line"]))
                        if len(logs) > 200:
                            logs = logs[-200:]
                        updated = True
                    elif msg_type == "final":
                        new_state.running = False
                        new_state.final_summary = msg.get("summary", "")
                        new_state.progress = _finalize_progress(new_state.progress)
                        updated = True

            # 2. 更新倒计时
            countdown_text = "-"
            if new_state.running and new_state.target_server_ts:
                remaining = new_state.target_server_ts - time.time()
                if remaining > 0:
                    countdown_text = f"⏰ {int(remaining)} 秒"
                else:
                    countdown_text = "🔥 已触发"

            # 3. 构造 UI 更新
            return (
                new_state,
                gr.update(value=("\n".join(logs[-30:]) if updated else None)),
                countdown_text,
                make_progress_rows(new_state.progress),
                _summary_text(new_state),
                _accounts_table_value(new_state),
            )

        timer.tick(
            fn=on_timer_tick,
            inputs=[state],
            outputs=[state, log_box, countdown_display, progress_table, top_summary, account_table],
        )

    return demo


def _accounts_table_value(state: ConsoleState) -> list[list]:
    """把 ConsoleState.accounts 转成 Dataframe value。"""
    rows = []
    for a in state.accounts:
        rows.append([
            a.get("name", ""),
            a.get("phone", ""),
            bool(a.get("enabled", True)),
            bool(a.get("has_token", False)),
        ])
    return rows


def _finalize_progress(progress: dict) -> dict:
    """任务结束时把所有 waiting 的账号标记为 failed。"""
    for name, p in progress.items():
        if p.state == "waiting":
            p.state = "failed"
            p.last_error = "任务结束未参与"
    return progress


def _summary_text(state: ConsoleState) -> str:
    """给顶部汇总框构造文本。"""
    if state.running:
        return "🔥 抢单进行中..."
    if state.final_summary:
        return state.final_summary
    return "(未开始)"


def main():
    parser = argparse.ArgumentParser(description="WebAuto 智谱抢购控制台")
    parser.add_argument("--port", type=int, default=7861, help="监听端口(默认 7861,避开 credential_panel 的 7860)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--share", action="store_true", help="生成 Gradio 公开分享链接")
    args = parser.parse_args()

    demo = build_console_ui()

    import gradio as gr
    print(f"🚀 智谱抢购控制台启动 → http://{args.host}:{args.port}")
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        theme=gr.themes.Soft(),
    )


if __name__ == "__main__":
    main()