"""抢购主编排器.

把配置加载、日志、NTP 同步、会话准备、调度、通知串成完整流程，并暴露给
``__main__`` 调用。
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from Core.Zhipu.browser import run_browser_for_accounts
from Core.Zhipu.config import AppConfig, load_config
from Core.Zhipu.crypto import CryptoError, SecretStore
from Core.Zhipu.group_scheduler import PlanGroupScheduler
from Core.Zhipu.logger import get_logger, setup_logger
from Core.Zhipu.notifier import Notifier
from Core.Zhipu.scheduler import GrabScheduler, GrabSummary
from Core.Zhipu.session import Session, SessionManager
from Core.Zhipu.timesync import TimeSync, build_time_sync

log = get_logger()


def sync_time(config: AppConfig) -> TimeSync:
    """统一的 NTP 校准入口。失败时降级到本地时钟(不推荐)。

    这个函数被 __main__.py 的 cmd_sync 和 Orchestrator._sync_time 共用,
    保证全流程只校准一次且行为一致。

    Returns:
        TimeSync 实例,offset_s 已校准(或为 0.0 表示降级)。
    """
    log.info(f"NTP 同步中({config.ntp_sync_times} 次)...")
    try:
        ts = build_time_sync(
            config.ntp_server, samples=config.ntp_sync_times
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"NTP 同步失败: {e},将使用本地时钟(不推荐)")
        return TimeSync(offset_s=0.0)

    drift_ms = abs(ts.offset_s) * 1000
    if drift_ms > config.ntp_max_drift_ms:
        log.warning(
            f"⚠️ 时钟漂移 {drift_ms:.1f}ms 超过阈值 "
            f"{config.ntp_max_drift_ms}ms,结果可能受影响"
        )
    else:
        log.info(f"时钟漂移 {drift_ms:.1f}ms,在可接受范围内")
    return ts


class Orchestrator:
    """端到端抢购编排器。"""

    def __init__(
        self,
        config: AppConfig,
        time_sync: Optional[TimeSync] = None,
    ) -> None:
        self.config = config
        # 支持外部注入(避免 NTP 校准两次)
        self.time_sync: Optional[TimeSync] = time_sync
        self.secret_store: Optional[SecretStore] = None
        self.sessions: list[Session] = []
        self.notifier = Notifier(config.notification)

    # ----------------------------------------------------------- 主入口

    async def run(self) -> GrabSummary:
        """执行完整的抢购流程。"""
        log.info(
            f"==== GLM Coding 抢购启动 | 套餐={self.config.target_plan.value} "
            f"周期={self.config.billing_cycle.value} "
            f"拼好模={self.config.use_pinhaomo} ===="
        )

        # 1. 加密凭证库
        self._open_secret_store()

        # 2. NTP 同步(如果外部没注入,自己校准一次)
        if self.time_sync is None:
            self.time_sync = await asyncio.to_thread(sync_time, self.config)

        # 3. 浏览器模式直接走备用方案
        if self.config.browser_mode:
            log.warning("启用 browser_mode，使用 Playwright 备用方案")
            await self._run_browser_mode()
            # 浏览器模式返回空 summary，通知在内部处理
            return GrabSummary()

        # 4. 构造会话 & 检测登录态
        await self._prepare_sessions()
        if not self.sessions:
            log.error("没有可用会话，抢购中止")
            await self.notifier.notify("❌ 抢购中止：没有可用会话（登录态全部失效）")
            return GrabSummary()

        # 5. 多套餐并行调度(共享 NTP + 账号会话)
        assert self.time_sync is not None
        group_sched = PlanGroupScheduler(self.config, self.time_sync)
        try:
            summary = await group_sched.run(self.sessions)
        finally:
            # 关闭所有会话
            await asyncio.gather(
                *(s.aclose() for s in self.sessions), return_exceptions=True
            )

        # 6. 通知
        await self.notifier.notify_summary(summary)
        return summary

    # ----------------------------------------------------------- 子步骤

    def _open_secret_store(self) -> None:
        try:
            self.secret_store = SecretStore(self.config.secret_store, ask=True)
            # 触发一次加载以校验口令
            self.secret_store.load()
            log.info("加密凭证库已就绪")
            # 诊断 enabled=true 但 SecretStore+config 里都没凭证的账号
            # (用户踩坑高发点:面板登录后账号名跟 config.yaml 对不上)
            missing: list[str] = []
            for acc in self.config.enabled_accounts:
                stored = self.secret_store.get_account(acc.name) or {}
                has_secret = bool(stored.get("token") or stored.get("cookie"))
                has_config = bool(acc.token or acc.cookie)
                if not (has_secret or has_config):
                    missing.append(acc.name)
            if missing:
                log.warning(
                    "以下 enabled 账号在加密凭证库和 config.yaml 里都没找到 "
                    "token/cookie,抢购时会被跳过: "
                    + ", ".join(missing)
                    + ". 请到面板「手机号登录(自动)」扫码/收码补凭证,"
                    "或手动补到 " + str(self.config.secret_store)
                )
            else:
                try:
                    stored_names = [a.get("name", "?") for a in self.secret_store.load()]
                    if stored_names:
                        log.info("加密凭证库已包含账号: " + ", ".join(stored_names))
                except Exception:
                    pass
        except CryptoError as e:
            log.warning(f"凭证库不可用（将以 config 明文凭证降级运行）: {e}")
            self.secret_store = None

    async def _prepare_sessions(self) -> None:
        mgr = SessionManager(self.config, self.secret_store)
        for account in self.config.enabled_accounts:
            client = mgr.build_client(account)
            session = Session(account=account, client=client)
            self.sessions.append(session)

        # 并发探测登录态
        alive_flags = await asyncio.gather(
            *(mgr.check_alive(s) for s in self.sessions)
        )

        # 失效账号直接排除。
        # 智谱没有开放短信登录 API,API 层的"自动重登"已删除,
        # 用户需在浏览器手动登录后把新 token/cookie 回填到凭证库。
        for session, alive in zip(self.sessions, alive_flags):
            if alive:
                continue
            log.error(
                f"[{session.account.name}] 登录态失效,跳过本账号。"
                f"请在浏览器登录 https://bigmodel.cn 后回填 token/cookie"
            )

        # 过滤掉仍然失效的会话
        self.sessions = [s for s in self.sessions if s.user_id]
        log.info(f"可用会话数: {len(self.sessions)}")

    async def _run_browser_mode(self) -> None:
        assert self.time_sync is not None
        accounts = self.config.enabled_accounts
        results = await run_browser_for_accounts(
            self.config, self.time_sync, accounts
        )
        lines = ["🌐 浏览器模式抢购结果"]
        any_ok = False
        for name, url in results:
            if url:
                any_ok = True
                lines.append(f"✅ {name}: {url}")
            else:
                lines.append(f"❌ {name}: 失败")
        await self.notifier.notify("\n".join(lines), success=any_ok)


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------


async def run_with_config(config_path: str) -> GrabSummary:
    """从配置文件加载并运行抢购。"""
    setup_logger()
    config = load_config(config_path)
    orch = Orchestrator(config)
    return await orch.run()
