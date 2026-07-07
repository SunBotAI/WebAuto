"""多套餐并行调度器.

把 AppConfig.plan_groups 里每组配置分别交给一个 GrabScheduler 跑,
所有组共享 TimeSync(只 NTP 校准一次)和账号会话(同一 token 复用)。

每组是一个临时 AppConfig:dataclasses.replace 风格覆盖 6 个字段,
其余字段(target_time / NTP / 通知 / retry / 代理 / 超时 / max_concurrent)
从原始 cfg 继承 —— 这样所有组都在同一时间点触发,共享账号并发上限。

结果聚合:每个 AccountResult.group 字段填充该组的 name(便于通知/UI 区分)。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Optional

from Core.Zhipu.config import AppConfig, PlanGroup
from Core.Zhipu.logger import get_logger
from Core.Zhipu.scheduler import AccountResult, GrabScheduler, GrabSummary
from Core.Zhipu.session import Session
from Core.Zhipu.timesync import TimeSync

log = get_logger()


# ---------------------------------------------------------------------------
# 临时配置构造
# ---------------------------------------------------------------------------


def _build_group_config(base: AppConfig, group: PlanGroup) -> AppConfig:
    """从 base 派生一个仅覆盖套餐组字段的临时 AppConfig。

    保留:target_time / ntp_* / notification / retry / adaptive_retry /
          proxy / request_timeout_s / max_concurrent / preheat_seconds /
          browser_mode / headless / secret_store。

    覆盖:target_plan / billing_cycle / pay_channel / use_pinhaomo /
          target_plans(fallback 顺序:[group.target_plan] + group.fallback_within_group)。
    """
    # pydantic BaseModel 用 .model_copy(update={...})
    # target_plans 顺序:组 target 在前,fallback 在后;target_plan 字段对齐第一个
    target_plans: list = [group.target_plan, *group.fallback_within_group]
    return base.model_copy(
        update={
            "target_plan": group.target_plan,
            "target_plans": target_plans,
            "billing_cycle": group.billing_cycle,
            "pay_channel": group.pay_channel,
            "use_pinhaomo": group.use_pinhaomo,
        }
    )


# ---------------------------------------------------------------------------
# 多组调度器
# ---------------------------------------------------------------------------


class PlanGroupScheduler:
    """多套餐并行调度器。

    用法::

        sched = PlanGroupScheduler(config, time_sync)
        summary = await sched.run(sessions, dry_run=False)
    """

    def __init__(
        self,
        config: AppConfig,
        time_sync: TimeSync,
    ) -> None:
        self.config = config
        self.ts = time_sync

    async def run(
        self,
        sessions: list[Session],
        *,
        dry_run: bool = False,
    ) -> GrabSummary:
        """并发执行所有 plan_groups,聚合结果。

        Args:
            sessions: 已就绪账号会话(被所有组共享)。
            dry_run: 透传给每组 GrabScheduler。

        Returns:
            合并后的 GrabSummary,每个 AccountResult.group 字段已填组名。
        """
        groups = self.config.enabled_plan_groups
        if not groups:
            log.warning("plan_groups 为空,跳过(应保证 model_validator 已折叠)")
            return GrabSummary(
                results=[
                    AccountResult(
                        account_name=s.account.name,
                        success=False,
                        error="no_plan_groups",
                        error_type="EmptyGroups",
                    )
                    for s in sessions
                ]
            )

        if not sessions:
            log.warning("没有可用账号会话,跳过所有组")
            return GrabSummary(results=[])

        log.info(
            f"==== 多套餐并行调度: {len(groups)} 组,"
            f" {len(sessions)} 账号共享 ===="
        )

        summary = GrabSummary(started_at=time.time())

        # 每组独立跑一个 GrabScheduler。
        # 组间用 asyncio.gather 并发,组内 max_concurrent 控制账号并发。
        group_tasks = [
            asyncio.create_task(
                self._run_one_group(group, sessions, dry_run=dry_run),
                name=f"grab-group:{group.name}",
            )
            for group in groups
        ]
        group_summaries = await asyncio.gather(*group_tasks, return_exceptions=True)

        # 聚合:每个组的 AccountResult 标记 group_name 后并入主 summary
        for group, sub in zip(groups, group_summaries):
            if isinstance(sub, Exception):
                log.error(f"[{group.name}] 组调度异常: {sub}")
                # 整组标记失败,每个账号一个失败 result
                for s in sessions:
                    summary.results.append(
                        AccountResult(
                            account_name=s.account.name,
                            success=False,
                            error=f"group {group.name} 异常: {sub}",
                            error_type="GroupSchedulerError",
                            group=group.name,
                        )
                    )
                continue
            assert isinstance(sub, GrabSummary)
            for r in sub.results:
                # 标记来源组(保留原 AccountResult,只覆盖 group)
                r.group = group.name
                summary.results.append(r)

        summary.finished_at = time.time()
        total_ms = (summary.finished_at - summary.started_at) * 1000
        log.info(
            f"多组调度完成: 成功 {summary.success_count}/{len(summary.results)},"
            f" 耗时 {total_ms:.0f}ms"
        )
        return summary

    async def _run_one_group(
        self,
        group: PlanGroup,
        sessions: list[Session],
        *,
        dry_run: bool,
    ) -> GrabSummary:
        """跑一个组(独立 GrabScheduler)。"""
        group_cfg = _build_group_config(self.config, group)
        log.info(
            f"[{group.name}] 启动组调度: "
            f"{group.target_plan.value}/{group_cfg.billing_cycle.value}/"
            f"{group.pay_channel.value} (pinhaomo={group.use_pinhaomo})"
        )
        sched = GrabScheduler(group_cfg, self.ts)
        return await sched.run(sessions, dry_run=dry_run)