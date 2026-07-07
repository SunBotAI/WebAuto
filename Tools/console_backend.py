"""智谱抢购控制台后端.

把控制台表单 → AppConfig → 启动 Scheduler → 把结果聚合成 UI 表格行。

这是 UI 和业务逻辑的桥:
- UI 拿到用户在 gradio 里填的账号、套餐、时间
- console_backend 把它组装成 Core/Zhipu 的 AppConfig
- 启动后台线程跑 GrabScheduler
- 进度通过 queue.Queue 推回 UI

设计原则:所有公开函数都是纯逻辑(单测友好),后台线程只做编排。
"""
from __future__ import annotations

import asyncio
import queue
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional


@dataclass
class AccountProgress:
    """单个账号的实时抢单进度。"""
    name: str = ""
    phone: str = ""
    state: str = "waiting"      # waiting / sending_code / grabbing / success / sold_out / risk_blocked / auth_error / failed / dry_run
    biz_id: str = ""
    order_no: str = ""
    pay_url: str = ""
    attempts: int = 0
    last_error: str = ""
    latency_ms: float = 0.0

    def to_row(self) -> list[str]:
        """转换成 Dataframe 的一行(7 列)。"""
        state_icon = {
            "waiting": "⏳ 等",
            "sending_code": "📤 发码",
            "grabbing": "🔄 抢中",
            "success": "✅ 成功",
            "sold_out": "❌ 售罄",
            "risk_blocked": "⚠ 风控",
            "auth_error": "🔒 登录失效",
            "failed": "❌ 失败",
            "dry_run": "🧪 dry",
        }.get(self.state, self.state)
        order = self.order_no or self.biz_id or "-"
        detail = self.last_error or f"{self.attempts} 次"
        if self.state == "success":
            detail = f"{int(self.latency_ms)}ms"
        elif self.pay_url:
            detail = self.pay_url[:30] + "..."
        return [
            self.name,
            state_icon,
            order,
            detail,
        ]


@dataclass
class ConsoleState:
    """gradio State 持久化的控制台内部状态。

    每个字段都从 UI 控件读/写。
    """
    # 多账号
    accounts: list[dict] = field(default_factory=list)
    # 每个 dict: {"name": "账号1", "phone": "138xxxxxxxx", "enabled": True, "token": "", "has_token": False}

    # 套餐
    target_plan: str = "Max"
    target_plans: list[str] = field(default_factory=lambda: ["Max", "Pro"])
    billing_cycle: str = "yearly"
    pay_channel: str = "alipay"
    downgrade: bool = True  # 是否失败自动降级下一档

    # ===== 多套餐配置(v5.x) =====
    # 每组是一组独立的抢购配置:{"name", "target_plan", "billing_cycle", "pay_channel",
    #                            "use_pinhaomo", "fallback_within_group", "notes", "enabled"}
    # 留空时由 state_to_appconfig_kwargs 自动从单套餐字段折叠成 1 个默认组。
    plan_groups: list[dict] = field(default_factory=list)

    # 时间
    time_mode: str = "countdown"  # countdown / absolute
    countdown_sec: int = 60
    absolute_time: str = ""

    # 高级
    max_concurrent: int = 4
    burst_count: int = 20
    quick_count: int = 10
    preheat_seconds: int = 5

    # 运行时
    running: bool = False
    started_at: Optional[float] = None
    target_server_ts: Optional[float] = None
    progress: dict[str, AccountProgress] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    final_summary: str = ""


def add_account(state: ConsoleState, name: str = "", phone: str = "") -> ConsoleState:
    """添加一个账号。返回新 state(gradio State 不可变更新)。"""
    new_state = ConsoleState(**asdict(state)) if state else ConsoleState()
    accounts = list(new_state.accounts)
    if not name:
        name = f"账号{len(accounts) + 1}"
    # 去重:同名跳过
    if any(a["name"] == name for a in accounts):
        return new_state
    accounts.append({
        "name": name,
        "phone": phone,
        "enabled": True,
        "token": "",
        "has_token": False,
    })
    new_state.accounts = accounts
    return new_state


def remove_account(state: ConsoleState, name: str) -> ConsoleState:
    """删除指定名字的账号。"""
    new_state = ConsoleState(**asdict(state)) if state else ConsoleState()
    new_state.accounts = [a for a in new_state.accounts if a["name"] != name]
    return new_state


def update_account_phone(state: ConsoleState, name: str, phone: str) -> ConsoleState:
    """更新指定账号的手机号。"""
    new_state = ConsoleState(**asdict(state)) if state else ConsoleState()
    for a in new_state.accounts:
        if a["name"] == name:
            a["phone"] = phone
            break
    return new_state


# ---------------------------------------------------------------------------
# 多套餐配置(plan_groups)操作
# ---------------------------------------------------------------------------

_PLAN_GROUP_DEFAULTS: dict[str, Any] = {
    "name": "",
    "target_plan": "Max",
    "billing_cycle": "yearly",
    "pay_channel": "alipay",
    "use_pinhaomo": True,
    "fallback_within_group": [],
    "notes": "",
    "enabled": True,
}


def _next_group_name(state: ConsoleState) -> str:
    """生成下一个默认组名(组1 / 组2 ...)。"""
    n = len(state.plan_groups) + 1
    return f"组{n}"


def add_plan_group(
    state: ConsoleState,
    name: str = "",
    target_plan: str = "Max",
    billing_cycle: str = "yearly",
    pay_channel: str = "alipay",
    use_pinhaomo: bool = True,
    fallback_within_group: Optional[list[str]] = None,
    notes: str = "",
) -> ConsoleState:
    """新增一个套餐配置组。返回新 state(gradio State 不可变更新)。

    Args:
        name: 组名;留空自动命名(组N)。
        fallback_within_group: 组内降级顺序的 tier 列表(如 ["Pro", "Lite"])。
    """
    new_state = ConsoleState(**asdict(state)) if state else ConsoleState()
    groups = list(new_state.plan_groups)
    if not name:
        name = _next_group_name(new_state)
    # 同名跳过
    if any(g.get("name") == name for g in groups):
        return new_state
    groups.append({
        **_PLAN_GROUP_DEFAULTS,
        "name": name,
        "target_plan": target_plan,
        "billing_cycle": billing_cycle,
        "pay_channel": pay_channel,
        "use_pinhaomo": use_pinhaomo,
        "fallback_within_group": list(fallback_within_group or []),
        "notes": notes,
    })
    new_state.plan_groups = groups
    return new_state


def remove_plan_group(state: ConsoleState, name: str) -> ConsoleState:
    """删除指定名字的套餐配置组。"""
    new_state = ConsoleState(**asdict(state)) if state else ConsoleState()
    new_state.plan_groups = [g for g in new_state.plan_groups if g.get("name") != name]
    return new_state


def toggle_plan_group(state: ConsoleState, name: str) -> ConsoleState:
    """切换指定套餐组的 enabled 状态。"""
    new_state = ConsoleState(**asdict(state)) if state else ConsoleState()
    for g in new_state.plan_groups:
        if g.get("name") == name:
            g["enabled"] = not g.get("enabled", True)
            break
    return new_state


def make_plan_group_rows(state: ConsoleState) -> list[list]:
    """把 state.plan_groups 转成 Dataframe 行(7 列)。

    列:组名 / 套餐 / 周期 / 支付 / 拼好模 / 降级 / 启用 / 备注
    """
    if not state.plan_groups:
        return [["默认(单组)", "(从单套餐字段)", "-", "-", "-", "-", "-", "-"]]
    rows = []
    for g in state.plan_groups:
        fallback = g.get("fallback_within_group") or []
        fallback_str = "→".join(fallback) if fallback else "-"
        rows.append([
            g.get("name", ""),
            g.get("target_plan", ""),
            g.get("billing_cycle", ""),
            g.get("pay_channel", ""),
            "✅" if g.get("use_pinhaomo", True) else "❌",
            fallback_str,
            "✅" if g.get("enabled", True) else "❌",
            g.get("notes", "")[:30],
        ])
    return rows


def resolve_target_ts(state: ConsoleState) -> float:
    """把时间模式(倒计时/绝对)解析成服务器时间戳。

    countdown: state.started_at + countdown_sec
    absolute: datetime(absolute_time)
    """
    if state.time_mode == "absolute" and state.absolute_time:
        try:
            naive = datetime.strptime(state.absolute_time, "%Y-%m-%d %H:%M:%S")
            return naive.timestamp()
        except (ValueError, TypeError):
            # 绝对时间解析失败 → 立即触发
            return time.time() + 0.5

    # 倒计时模式:依赖 started_at
    if state.started_at is None:
        return time.time() + 0.5
    return state.started_at + state.countdown_sec


def state_to_appconfig_kwargs(state: ConsoleState) -> dict[str, Any]:
    """把 ConsoleState 转换为 AppConfig 的 kwargs(待 scheduler 用)。

    target_time 字段由 caller 单独设置(因为依赖 started_at)。

    多套餐行为(v5.x):
      - state.plan_groups 非空时,直接用作 plan_groups 字段
        (AppConfig model_validator 会再做一次 enabled 过滤)
      - state.plan_groups 为空时,折叠成 1 个默认组(用单套餐字段),
        行为与改动前一致 — 走 target_plan + target_plans 路径
    """
    accounts = [
        {
            "name": a["name"],
            "phone": a["phone"],
            "token": a.get("token", ""),
            "enabled": a.get("enabled", True),
        }
        for a in state.accounts
        if a.get("phone") or a.get("token")  # 至少要有手机号或 token
    ]

    if state.plan_groups:
        # 多组路径:直接传 plan_groups,让 AppConfig model_validator 接管
        # 单套餐字段不再参与(AppConfig 会忽略 target_plan 兜底逻辑)
        plan_groups = [dict(g) for g in state.plan_groups if g.get("enabled", True)]
        return {
            "accounts": accounts,
            "plan_groups": plan_groups,
            "max_concurrent": state.max_concurrent,
            "preheat_seconds": state.preheat_seconds,
        }

    # 单组路径(向后兼容):用旧字段
    return {
        "accounts": accounts,
        "target_plan": state.target_plan,
        "target_plans": state.target_plans if state.downgrade else [state.target_plan],
        "billing_cycle": state.billing_cycle,
        "pay_channel": state.pay_channel,
        "max_concurrent": state.max_concurrent,
        "preheat_seconds": state.preheat_seconds,
    }


def make_progress_rows(progress: dict[str, AccountProgress]) -> list[list[str]]:
    """把所有账号进度转成 Dataframe 行。"""
    if not progress:
        return [["(无账号)", "-", "-", "-"]]
    return [p.to_row() for p in progress.values()]


def make_summary(state: ConsoleState) -> str:
    """汇总抢单结果给 UI 顶部显示。"""
    if not state.running and not state.final_summary:
        return ""
    if state.running:
        elapsed = ""
        if state.started_at:
            elapsed = f"已运行 {int(time.time() - state.started_at)}s"
        return f"🔥 抢单中...{elapsed}"
    return state.final_summary


# ============================================================
# 后台调度:把 Scheduler 包成"线程 + 进度队列"
# ============================================================

# 全局 dict:job_id -> (stop_event, queue)
# console.py 用它管理正在运行的任务,gr.State 装不下 queue.Queue
ACTIVE_JOBS: dict[str, tuple["threading.Event", "queue.Queue"]] = {}


@dataclass
class ConsoleJob:
    """一次抢单任务。"""
    state: ConsoleState
    progress_queue: queue.Queue
    stop_event: threading.Event
    time_sync_factory: Any  # callable() -> TimeSync

    def is_stop_requested(self) -> bool:
        return self.stop_event.is_set()


def run_console_job(job: ConsoleJob) -> None:
    """后台线程入口:跑 Scheduler,把结果推到 progress_queue。

    这是纯编排,不写业务逻辑。
    """
    from Core.Zhipu.config import AppConfig
    from Core.Zhipu.scheduler import GrabScheduler, AccountResult

    state = job.state
    q = job.progress_queue
    log = lambda msg: q.put({"type": "log", "line": f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"})

    log(f"启动抢单任务:target={state.target_plan}/{state.billing_cycle}, "
        f"accounts={len(state.accounts)}")

    if not state.accounts:
        q.put({"type": "final", "summary": "❌ 没有账号,请先加账号"})
        return

    # 1. NTP 校准
    log("NTP 校准中...")
    try:
        from Core.Zhipu.orchestrator import sync_time
        ts = sync_time(_make_minimal_config())
    except Exception as e:
        log(f"⚠ NTP 校准失败: {e},使用本地时钟")
        from Core.Zhipu.timesync import TimeSync
        ts = TimeSync(offset_s=0.0)
    q.put({"type": "ts", "time_sync": ts})

    # 2. 构造 AppConfig
    cfg_kwargs = state_to_appconfig_kwargs(state)
    cfg_kwargs["target_time"] = _format_target_time(state)
    try:
        cfg = AppConfig(**cfg_kwargs)
    except Exception as e:
        q.put({"type": "final", "summary": f"❌ 配置构造失败: {e}"})
        return

    # 3. 构造 sessions(从 SecretStore 读 token)
    from Core.Zhipu.session import SessionManager
    from Core.Zhipu.config import load_config  # noqa
    sm = SessionManager(cfg, secret_store=None)
    sessions = []
    for acc in cfg.accounts:
        from Core.Zhipu.http_client import ApiClient
        client = ApiClient(
            cfg,
            token=acc.get("token") or "",
            cookie="",
            account_name=acc["name"],
        )
        from Core.Zhipu.session import Session
        sess = Session(account=acc, client=client, user_id="")
        sessions.append(sess)

    # 4. 启动 scheduler
    log(f"启动调度器:target_ts={resolve_target_ts(state):.0f}, "
        f"max_concurrent={cfg.max_concurrent}, preheat={cfg.preheat_seconds}s")

    scheduler = GrabScheduler(cfg, ts)

    # 进度回调(简化版:scheduler 完成后我们一次性聚合结果)
    try:
        summary = _run_scheduler_sync(scheduler, sessions, job, log)
    except Exception as e:
        q.put({"type": "final", "summary": f"❌ 调度异常: {e}"})
        return

    # 5. 把 summary 转成 AccountProgress
    for r in summary.results:
        progress = state.progress.get(r.account_name) or AccountProgress(name=r.account_name)
        progress.latency_ms = r.latency_ms
        if r.success:
            progress.state = "success"
            progress.order_no = r.order.order_id if r.order else ""
            progress.pay_url = r.order.pay_url if r.order else ""
            progress.biz_id = r.order.biz_id if r.order else ""
        else:
            progress.state = _error_type_to_state(r.error_type or "failed")
            progress.last_error = r.error or ""
        state.progress[r.account_name] = progress

    success_count = summary.success_count
    total = len(summary.results)
    q.put({
        "type": "final",
        "summary": f"抢单结束:{success_count}/{total} 成功,{total - success_count} 失败",
    })


def _make_minimal_config():
    """给 sync_time() 用的最小 config(不需要真实账号)。"""
    from Core.Zhipu.config import AppConfig, Account
    return AppConfig(
        accounts=[Account(name="ntp_probe", phone="")],
        target_plan="Max",
        billing_cycle="yearly",
        pay_channel="alipay",
    )


def _format_target_time(state: ConsoleState) -> str:
    """把状态的时间转成 AppConfig.target_time 接受的格式。"""
    if state.time_mode == "absolute" and state.absolute_time:
        return state.absolute_time
    # 倒计时模式:target_time 不重要(我们直接用 sleep_until),给个未来时间
    future = datetime.now() + timedelta(seconds=state.countdown_sec + state.preheat_seconds + 10)
    return future.strftime("%Y-%m-%d %H:%M:%S")


def _run_scheduler_sync(scheduler, sessions, job, log):
    """同步跑 scheduler.run(),带取消检查。"""
    # scheduler.run 是 async,我们跑 asyncio.run
    # 同时每 N ms 检查 stop_event
    import asyncio

    async def _wrapper():
        task = asyncio.create_task(scheduler.run(sessions))
        while not task.done():
            await asyncio.sleep(0.3)
            if job.is_stop_requested():
                task.cancel()
                log("⚠ 用户请求取消")
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                return _fake_cancelled_summary(sessions)
            # 把 progress 推到队列(每个账号当前 attempts 数)
            _push_progress(job, scheduler)
        return task.result()

    return asyncio.run(_wrapper())


def _fake_cancelled_summary(sessions):
    """用户取消时构造一个空的 summary,所有账号标记为 failed。"""
    from Core.Zhipu.scheduler import GrabSummary, AccountResult
    return GrabSummary(results=[
        AccountResult(account_name=s.account.name, success=False,
                     error="user cancelled", error_type="Cancelled", latency_ms=0.0)
        for s in sessions
    ])


def _push_progress(job, scheduler):
    """把当前每个账号的状态推到队列(scheduler 内部 state 不能直接拿,我们只发进度事件)。

    简化方案:这里只推日志,具体进度在 _run_scheduler_sync 完成后汇总一次。
    """
    pass  # 实际进度在 scheduler 完成后从 summary 聚合


def _error_type_to_state(error_type: str) -> str:
    """把 Scheduler 的 error_type 转成 UI state。"""
    return {
        "SoldOutError": "sold_out",
        "AuthError": "auth_error",
        "RiskBlockedError": "risk_blocked",
        "Cancelled": "failed",
        "NetworkError": "failed",
    }.get(error_type, "failed")