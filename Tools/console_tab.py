"""Console Tab — Gradio Tab 实现，供 console.py 和 webauto_web.py 共用。

不要直接 launch 此文件，用 console.py 或 webauto_web.py 启动。
"""
from __future__ import annotations

import asyncio
import queue
import sys
import threading
import time
import uuid
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
    remove_account,
    remove_plan_group,
    resolve_target_ts,
    toggle_plan_group,
    ACTIVE_JOBS,
    ConsoleJob,
    run_console_job,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _format_log_line(line: str) -> str:
    ts = datetime.now().strftime("%H:%M:%S")
    return f"[{ts}] {line}"


def _accounts_table_value(state: ConsoleState) -> list[list]:
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
    for name, p in progress.items():
        if p.state == "waiting":
            p.state = "failed"
            p.last_error = "任务结束未参与"
    return progress


def _summary_text(state: ConsoleState) -> str:
    if state.running:
        return "🔥 抢单进行中..."
    if state.final_summary:
        return state.final_summary
    return "(未开始)"


def build_console_tab() -> None:
    """
    在当前 Gradio Blocks 上下文中追加 Console Tab。

    调用方式（在 Gradio with Block 内）:
        with gr.Tab("⚡ Console"):
            build_console_tab()
    """
    import gradio as gr
    # 模块级 bridge:跨函数调用同步账号列表(SMS 已下线但 add_account 仍依赖)
    global _accounts_bridge  # noqa: PLW0603
    _accounts_bridge = {"state": None}

    initial_state = ConsoleState()
    initial_state = add_account(initial_state)
    initial_state = add_plan_group(
        initial_state,
        name="默认",
        target_plan="Max",
        billing_cycle="yearly",
        pay_channel="alipay",
    )

    gr.Markdown(
        "# 🛡️ WebAuto 智谱 GLM Coding 抢购控制台\n"
        "所有参数在页面配置,不用改 yaml。点 [🔥 开始抢] 后等倒计时到点自动下单。"
    )

    # ── 顶部:手机号+短信码登录(自动) ─────────────────────────────────
    # 流程:
    #   1) 填账号名+手机号,点"🚀 启动登录"
    #   2) WebAuto 本地拉带指纹 Chromium(走 Core.AntiDetect)
    #   3) 自动: 打开智谱首页 → 点"登录/注册" → 输手机号 → 点"获取验证码"
    #   4) 腾讯防水墙按顺序点汉字验证弹窗出现 — **你用鼠标在浏览器里点**
    #      (弹窗是浏览器层面的,面板只显示截图给你确认是哪张)
    #   5) 验证通过 → 智谱下发短信到你手机 → **你在面板的 6 位码输入框里手输**
    #   6) 自动: 提交登录 → 抽 token/cookie → 加密落 .secrets.enc
    with gr.Accordion("📱 手机号登录(自动) - 指纹浏览器 + 腾讯点选 + 短信码", open=False):
        from Tools.credential_backend import CredentialBackend
        _cred_backend_phone = CredentialBackend()

        # 跨 handler 共享:task handle / sms_future
        _phone_login_state: dict = {"task": None, "sms_future": None, "running": False, "provider": None}

        with gr.Row():
            with gr.Column(scale=1):
                phone_name = gr.Textbox(label="账号名", placeholder="主账号")
                phone_num = gr.Textbox(label="手机号(国内 11 位)", placeholder="138xxxxxxxx")
                with gr.Row():
                    phone_start = gr.Button("🚀 启动登录", variant="primary")
                    phone_cancel = gr.Button("🛑 取消", variant="stop")
                phone_stage = gr.Textbox(label="阶段", value="(未开始)", interactive=False)
            with gr.Column(scale=1):
                phone_captcha = gr.Image(label="腾讯点选验证(浏览器里点)", height=200)
                phone_sms = gr.Textbox(label="短信 6 位码(收到后填这里)", max_lines=1,
                                        placeholder="短信里的 6 位数字")
                phone_submit = gr.Button("📨 提交短信码", variant="primary")
                phone_status = gr.Textbox(label="状态", value="", interactive=False, lines=5)

        def _do_phone_start(name, phone):
            if _phone_login_state["running"]:
                return ("已在运行中", None, "⚠️ 已有一个登录任务在跑")
            if not name.strip():
                return ("(未开始)", None, "⚠️ 账号名必填")
            if not phone or len(phone) < 11:
                return ("(未开始)", None, "⚠️ 手机号格式错(11 位)")

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
                    raise RuntimeError("no loop")
            except RuntimeError:
                loop = _aio.new_event_loop()
                _aio.set_event_loop(loop)

            sms_future = loop.create_future()
            async def _wrap_provider() -> str:
                return await sms_future
            _phone_login_state["provider"] = _wrap_provider

            async def _go():
                return await _cred_backend_phone.phone_login_and_save(
                    account_name=name,
                    phone=phone,
                    sms_code_provider=_wrap_provider,
                    timeout_sec=180,
                    progress_callback=_cb,
                )

            task = loop.create_task(_go())
            _phone_login_state["task"] = task
            _phone_login_state["sms_future"] = sms_future
            _phone_login_state["running"] = True

            # 等几秒看 progress(不阻塞面板太久)
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

        def _do_phone_submit_sms(code):
            fut = _phone_login_state.get("sms_future")
            if fut is None or fut.done():
                return "⚠️ 没有等待中的登录任务(可能已超时/取消)"
            if not code or len(code.strip()) < 4:
                return "⚠️ 短信码至少 4 位"
            fut.get_loop().call_soon_threadsafe(fut.set_result, code.strip())
            return "✅ 短信码已提交,等待登录..."

        def _do_phone_cancel():
            fut = _phone_login_state.get("sms_future")
            task = _phone_login_state.get("task")
            if fut is not None and not fut.done():
                fut.get_loop().call_soon_threadsafe(fut.set_result, "")
            if task is not None and not task.done():
                task.cancel()
            _phone_login_state["running"] = False
            return "已取消"

        def _do_phone_poll():
            task = _phone_login_state.get("task")
            if task is None:
                return ("(未开始)", "未启动登录")
            if task.done():
                try:
                    r = task.result()
                except Exception as e:
                    _phone_login_state["running"] = False
                    return ("error", f"异常: {e}")
                _phone_login_state["running"] = False
                if r.get("success"):
                    return ("done", f"✅ 登录成功 → {r.get('message', '')}\nuser_id: {r.get('user_id', '')}")
                return ("failed", f"❌ {r.get('message', r.get('stage', 'failed'))}")
            return ("waiting", "流程进行中... 等待:浏览器点汉字 + 面板填 6 位码")

        phone_start.click(fn=_do_phone_start, inputs=[phone_name, phone_num],
                          outputs=[phone_stage, phone_captcha, phone_status])
        phone_submit.click(fn=_do_phone_submit_sms, inputs=[phone_sms], outputs=[phone_status])
        phone_cancel.click(fn=_do_phone_cancel, outputs=[phone_status])
        phone_poll_timer = gr.Timer(value=3)
        phone_poll_timer.tick(fn=_do_phone_poll, outputs=[phone_stage, phone_status])


    # ── 套餐配置(多组) ───────────────────────────────────────────
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🎯 套餐配置(多组 · 并行)")
            gr.Markdown("每组是一组独立的抢购配置(目标套餐/周期/支付),点 [开始抢] 后所有 enabled 组并发执行,共享 NTP + 账号 token。")
            plan_group_table = gr.Dataframe(
                headers=["组名", "套餐", "周期", "支付", "拼好模", "降级", "启用", "备注"],
                datatype=["str", "str", "str", "str", "str", "str", "str", "str"],
                value=make_plan_group_rows(initial_state),
                interactive=False,
            )
            with gr.Row():
                new_group_name = gr.Textbox(label="组名", placeholder="(留空自动编号)", scale=2)
                new_group_plan = gr.Dropdown(choices=["Max", "Pro", "Lite"], value="Max", label="目标套餐", scale=2)
                new_group_cycle = gr.Dropdown(choices=["yearly", "quarterly", "monthly"], value="yearly", label="周期", scale=2)
                new_group_channel = gr.Dropdown(choices=["alipay", "weChat_pay", "balance_pay"], value="alipay", label="支付", scale=2)
            with gr.Row():
                new_group_fallback = gr.Textbox(label="组内降级顺序", placeholder="Pro,Lite(逗号分隔,留空=不降级)", scale=4)
                add_group_btn = gr.Button("➕ 添加组", variant="primary", scale=1)
            with gr.Row():
                del_group_name = gr.Textbox(label="要删除的组名", scale=3)
                del_group_btn = gr.Button("🗑 删除组", variant="stop", scale=1)
                toggle_group_name = gr.Textbox(label="切换启用状态的组名", scale=3)
                toggle_group_btn = gr.Button("🔁 切换启用", scale=1)

    # ── 左:参数 + 账号 ────────────────────────────────────────────
    with gr.Row():
        with gr.Column(scale=2):
            gr.Markdown("### ⚙️ 单套餐视图(留空则被多组配置覆盖)")
            plan = gr.Dropdown(choices=["Max", "Pro", "Lite"], value="Max", label="目标套餐(legacy)")
            cycle = gr.Dropdown(choices=["yearly", "quarterly", "monthly"], value="yearly", label="计费周期(legacy)")
            downgrade = gr.Checkbox(value=True, label="降级:失败自动试下一档(Max → Pro → Lite,legacy)")
            gr.Markdown("---")
            time_mode = gr.Radio(
                choices=[("⏱ 倒计时", "countdown"), ("📅 绝对时间", "absolute")],
                value="countdown", label="开抢时间模式",
            )
            with gr.Row():
                countdown_sec = gr.Number(value=60, label="倒计时秒数", minimum=5, maximum=3600, visible=True)
                absolute_time = gr.Textbox(label="绝对时间(YYYY-MM-DD HH:MM:SS)", value="", placeholder="2026-07-15 10:00:00", visible=False)
            gr.Markdown("---")
            pay_channel = gr.Dropdown(choices=["alipay", "weChat_pay", "balance_pay"], value="alipay", label="支付方式")
            max_concurrent = gr.Slider(minimum=1, maximum=10, value=4, step=1, label="并发账号数")
            with gr.Accordion("⚙️ 高级(进阶)", open=False):
                burst_count = gr.Slider(minimum=1, maximum=50, value=20, step=1, label="零延迟爆发次数(前 N 次争首批)")
                quick_count = gr.Slider(minimum=1, maximum=30, value=10, step=1, label="快速重试次数")
                preheat_seconds = gr.Slider(minimum=1, maximum=30, value=5, step=1, label="预热连接秒数")

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
            gr.Markdown("💡 token 状态从 .secrets.enc 自动读取。没有 token 的账号会被跳过,先在凭证管理面板登录。")

    # ── 中:抢单状态 ──────────────────────────────────────────────
    gr.Markdown("### 🔥 抢单状态")
    with gr.Row():
        top_summary = gr.Textbox(label="汇总", value="(未开始)", interactive=False)
        countdown_display = gr.Textbox(label="倒计时 / 状态", value="-", interactive=False)
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

    # ── 底部:日志 ─────────────────────────────────────────────────
    gr.Markdown("### 📜 实时日志")
    log_box = gr.Textbox(value="", interactive=False, lines=10, max_lines=30, autoscroll=True)

    # ── 状态对象 ──────────────────────────────────────────────────
    state = gr.State(value=initial_state)
    _accounts_bridge["state"] = initial_state
    ACTIVE_JOBS.clear()

    # 时间模式切换
    def on_time_mode_change(mode):
        return gr.update(visible=(mode == "countdown")), gr.update(visible=(mode == "absolute"))

    time_mode.change(fn=on_time_mode_change, inputs=time_mode, outputs=[countdown_sec, absolute_time])

    # 添加账号
    def on_add(state_val, name, phone):
        new_state = add_account(state_val, name=name, phone=phone)
        return new_state, _accounts_table_value(new_state)

    add_btn.click(fn=on_add, inputs=[state, new_name, new_phone], outputs=[state, account_table])

    # 删除账号
    def on_delete(state_val, name):
        new_state = remove_account(state_val, name)
        return new_state, _accounts_table_value(new_state)

    del_btn.click(fn=on_delete, inputs=[state, del_name], outputs=[state, account_table])

    # 添加套餐配置组
    def on_add_group(state_val, name, plan_v, cycle_v, channel_v, fallback_str):
        fallback_list = [x.strip() for x in (fallback_str or "").split(",") if x.strip()]
        new_state = add_plan_group(state_val, name=name, target_plan=plan_v, billing_cycle=cycle_v, pay_channel=channel_v, fallback_within_group=fallback_list)
        return new_state, make_plan_group_rows(new_state)

    add_group_btn.click(fn=on_add_group, inputs=[state, new_group_name, new_group_plan, new_group_cycle, new_group_channel, new_group_fallback], outputs=[state, plan_group_table])

    # 删除套餐配置组
    def on_del_group(state_val, name):
        new_state = remove_plan_group(state_val, name)
        return new_state, make_plan_group_rows(new_state)

    del_group_btn.click(fn=on_del_group, inputs=[state, del_group_name], outputs=[state, plan_group_table])

    # 切换套餐组启用
    def on_toggle_group(state_val, name):
        new_state = toggle_plan_group(state_val, name)
        return new_state, make_plan_group_rows(new_state)

    toggle_group_btn.click(fn=on_toggle_group, inputs=[state, toggle_group_name], outputs=[state, plan_group_table])

    # ── 开始抢 ────────────────────────────────────────────────────
    def _start_job(state_val, dry_run):
        if state_val.running:
            return state_val, gr.update(value="⚠ 已有抢单任务在运行,请先取消"), gr.update(value="-"), gr.update()
        if not state_val.accounts:
            return state_val, gr.update(value="⚠ 请先添加账号"), gr.update(value="-"), gr.update()

        stop_event = threading.Event()
        progress_q = queue.Queue()
        job_id = uuid.uuid4().hex[:8]
        ACTIVE_JOBS[job_id] = (stop_event, progress_q)

        job = ConsoleJob(state=state_val, progress_queue=progress_q, stop_event=stop_event, time_sync_factory=None)

        def _run_in_thread():
            run_console_job(job)
            ACTIVE_JOBS.pop(job_id, None)

        t = threading.Thread(target=_run_in_thread, daemon=True)
        t.start()

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

    start_btn.click(fn=_start_job, inputs=[state, gr.State(value=False)], outputs=[state, top_summary, countdown_display, gr.State()])
    dryrun_btn.click(fn=_start_job, inputs=[state, gr.State(value=True)], outputs=[state, top_summary, countdown_display, gr.State()])

    # ── 取消抢单 ──────────────────────────────────────────────────
    def on_cancel(state_val):
        count = 0
        for stop_event, _ in ACTIVE_JOBS.values():
            if not stop_event.is_set():
                stop_event.set()
                count += 1
        return state_val, f"已请求取消 {count} 个任务"

    cancel_btn.click(fn=on_cancel, inputs=[state], outputs=[state, top_summary])

    # ── Timer 轮询 ────────────────────────────────────────────────
    timer = gr.Timer(value=1.0, active=True)

    def on_timer_tick(state_val):
        new_state = ConsoleState(**asdict(state_val))
        logs = list(new_state.logs)
        updated = False

        bridge = _accounts_bridge.get("state")
        if bridge is not None and len(bridge.accounts) > len(new_state.accounts):
            new_state = ConsoleState(**asdict(bridge))
            updated = True

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

        countdown_text = "-"
        if new_state.running and new_state.target_server_ts:
            remaining = new_state.target_server_ts - time.time()
            if remaining > 0:
                countdown_text = f"⏰ {int(remaining)} 秒"
            else:
                countdown_text = "🔥 已触发"

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
