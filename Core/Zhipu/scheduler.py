"""定时抢购调度器.

职责：
- 把目标时间字符串解析成时间戳（基于 NTP 校准后的服务器时间）
- 在 T - preheat 时预热连接
- 在 T - 3s 发送预请求（可选）
- 在 T + offset 时精确触发下单
- 多账号并发执行（受 max_concurrent 限制）
- 汇总结果交给上层通知

时间线（以服务器时间为准）::

    T-5s   预热连接（TLS + 连接池）
    T-3s   预取产品信息 / 检查限购（部分链路提前跑）
    T+0    发起下单请求
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from Core.Zhipu.api import BigModelApi, OrderResult
from Core.Zhipu.config import AppConfig
from Core.Zhipu.exceptions import (
    AuthError,
    ZhipuError,
    NetworkError,
    RateLimitedError,
    RiskBlockedError,
    SoldOutError,
    CheckExpireError,
)
from Core.Zhipu.http_client import ApiClient
from Core.Zhipu.logger import get_logger
from Core.Zhipu.session import Session
from Core.Zhipu.timesync import TimeSync

log = get_logger()


# ---------------------------------------------------------------------------
# 结果
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AccountResult:
    account_name: str
    success: bool
    order: Optional[OrderResult] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    latency_ms: float = 0.0
    group: str = ""  # PlanGroup.name;空字符串表示单组模式(向后兼容)


@dataclass(slots=True)
class GrabSummary:
    results: list[AccountResult] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def any_success(self) -> bool:
        return any(r.success for r in self.results)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.success)


# ---------------------------------------------------------------------------
# 调度器
# ---------------------------------------------------------------------------


class GrabScheduler:
    """抢购调度器。

    用法::

        sched = GrabScheduler(config, time_sync)
        summary = await sched.run(sessions)

        # dry-run:不实际下单,只走时间校准 + 预热 + 等待触发点 + 验证时序
        summary = await sched.run(sessions, dry_run=True)
    """

    def __init__(self, config: AppConfig, time_sync: TimeSync) -> None:
        self.config = config
        self.ts = time_sync

    # ----------------------------------------------------------- 时间解析

    def _target_server_ts(self) -> float:
        """把 config.target_time（本地时间字符串）转成「服务器时间戳」。

        target_time 视为用户期望的服务器开抢时间。我们用本地解析得到一个
        本地时间戳，再换算成服务器时间戳以供 :class:`TimeSync` 使用。
        """
        naive = datetime.strptime(self.config.target_time, "%Y-%m-%d %H:%M:%S")
        # naive -> 本地时间戳
        local_ts = naive.timestamp()
        # 加上时间偏移（负值=提前）得到目标服务器时间戳
        return local_ts + self.ts.offset_s + self.config.time_offset_ms / 1000.0

    # ----------------------------------------------------------- 主流程

    async def run(
        self, sessions: list[Session], *, dry_run: bool = False
    ) -> GrabSummary:
        """等待到目标时间,并发执行抢购。

        Args:
            sessions: 已就绪的账号会话列表。
            dry_run: True 时只走时序校准 + 预热 + 等待触发点,**不实际下单**。
                     用于在真抢前验证时序正确、配置无误。dry_run 模式下所有
                     账号返回 success=False 的虚拟结果。
        """
        target_ts = self._target_server_ts()
        preheat_ts = target_ts - self.config.preheat_seconds

        log.info(
            f"目标触发（服务器时间）: "
            f"{datetime.fromtimestamp(target_ts - self.ts.offset_s).strftime('%H:%M:%S.%f')[:-3]} "
            f"+ offset {self.config.time_offset_ms}ms "
            f"{'[DRY-RUN]' if dry_run else ''}"
        )

        # 预热阶段（提前 preheat_seconds）
        now = self.ts.server_now()
        wait_preheat = preheat_ts - now
        if wait_preheat > 0:
            log.info(
                f"等待 {wait_preheat:.2f}s 后开始预热连接 "
                f"(preheat={self.config.preheat_seconds}s)"
            )
            await self.ts.sleep_until(preheat_ts)
        else:
            log.warning("已过预热时间点，立即开始预热")

        # 并发预热每个会话的连接池
        await asyncio.gather(
            *(self._preheat(s) for s in sessions),
            return_exceptions=True,
        )

        # dry-run:验证触发点可达后直接返回,不发实际请求
        if dry_run:
            log.info("[DRY-RUN] 预热完成,跳过实际下单,返回虚拟结果")
            summary = GrabSummary(started_at=time.time())
            summary.results = [
                AccountResult(
                    account_name=s.account.name,
                    success=False,
                    error="dry_run",
                    error_type="DryRun",
                    latency_ms=0.0,
                )
                for s in sessions
            ]
            summary.finished_at = time.time()
            return summary

        # 等到精确触发点
        now = self.ts.server_now()
        wait_fire = target_ts - now
        if wait_fire > 0:
            log.info(f"距离触发还有 {wait_fire * 1000:.0f}ms，进入精确等待")
            await self.ts.sleep_until(target_ts)

        # 触发！并发执行
        summary = GrabSummary(started_at=time.time())
        semaphore = asyncio.Semaphore(self.config.max_concurrent)
        tasks = [
            asyncio.create_task(self._grab_one(s, semaphore))
            for s in sessions
        ]
        summary.results = await asyncio.gather(*tasks)
        summary.finished_at = time.time()

        total_ms = (summary.finished_at - summary.started_at) * 1000
        log.info(
            f"抢购结束：成功 {summary.success_count}/{len(summary.results)}，"
            f"耗时 {total_ms:.0f}ms"
        )
        return summary

    # ----------------------------------------------------------- 单账号

    async def _preheat(self, session: Session) -> None:
        try:
            await session.client.preheat()
            log.debug(f"[{session.account.name}] 连接预热完成")
        except Exception as e:  # noqa: BLE001
            log.warning(f"[{session.account.name}] 预热异常（忽略）: {e}")

    async def _grab_one(
        self, session: Session, sem: asyncio.Semaphore
    ) -> AccountResult:
        """单账号抢购入口:根据 config.adaptive_retry.use_preview_check_mode 选择模式。"""
        async with sem:
            t0 = time.perf_counter()
            api = BigModelApi(session.client, self.config)
            if self.config.adaptive_retry.use_preview_check_mode:
                # qtaxm 模式:preview+check,EXPIRE 自动重试
                return await self._grab_with_adaptive_retry(session, api, t0)
            else:
                # 原 batch-preview 模式:单次跑完整链路
                return await self._grab_with_simple_retry(session, api, t0)

    async def _grab_with_simple_retry(
        self,
        session: Session,
        api: BigModelApi,
        t0: float,
    ) -> AccountResult:
        """原 batch-preview 模式:只跑一次 run_purchase_chain。"""
        try:
            order = await api.run_purchase_chain()
            latency = (time.perf_counter() - t0) * 1000
            log.success(
                f"[{session.account.name}] 抢购成功！"
                f"orderId={order.order_id} 耗时 {latency:.0f}ms"
            )
            return AccountResult(
                account_name=session.account.name,
                success=True,
                order=order,
                latency_ms=latency,
            )
        except SoldOutError as e:
            latency = (time.perf_counter() - t0) * 1000
            log.warning(
                f"[{session.account.name}] 售罄/限购: {e} ({latency:.0f}ms)"
            )
            return _fail(session, e, "SoldOutError", latency)
        except AuthError as e:
            latency = (time.perf_counter() - t0) * 1000
            log.error(f"[{session.account.name}] 登录态失效: {e}")
            return _fail(session, e, "AuthError", latency)
        except RiskBlockedError as e:
            latency = (time.perf_counter() - t0) * 1000
            log.error(f"[{session.account.name}] 被风控拦截: {e}")
            return _fail(session, e, "RiskBlockedError", latency)
        except RateLimitedError as e:
            latency = (time.perf_counter() - t0) * 1000
            log.warning(f"[{session.account.name}] 限流: {e}")
            return _fail(session, e, "RateLimitedError", latency)
        except NetworkError as e:
            latency = (time.perf_counter() - t0) * 1000
            log.error(f"[{session.account.name}] 网络错误: {e}")
            return _fail(session, e, "NetworkError", latency)
        except ZhipuError as e:
            latency = (time.perf_counter() - t0) * 1000
            log.error(f"[{session.account.name}] 抢购失败: {e}")
            return _fail(session, e, type(e).__name__, latency)
        except Exception as e:  # noqa: BLE001
            latency = (time.perf_counter() - t0) * 1000
            log.exception(f"[{session.account.name}] 未预期异常")
            return _fail(session, e, "Unexpected", latency)

    async def _grab_with_adaptive_retry(
        self,
        session: Session,
        api: BigModelApi,
        t0: float,
    ) -> AccountResult:
        """qtaxm 风格:自适应间隔重试。

        时间线(参考 config.adaptive_retry):
          第 1..burst_count 次: 零延迟爆发
          第 burst+1..burst+quick_count 次: quick_retry_ms 间隔 (默认 30ms)
          之后: slow_retry_ms ± jitter_pct 抖动 (默认 100ms ± 30%)

        退出条件:
          - 成功 → 立即返回 AccountResult(success=True)
          - SoldOutError → 立即返回失败(该档位真没了)
          - AuthError / RiskBlockedError → 立即返回(无意义重试)
          - 达到 max_total_attempts → 返回失败
        """
        policy = self.config.adaptive_retry
        name = session.account.name
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt < policy.max_total_attempts:
            attempt += 1

            # 计算本次的延迟
            if attempt <= policy.burst_count:
                # 零延迟爆发阶段
                delay_s = 0.0
                phase = "burst"
            elif attempt <= policy.burst_count + policy.quick_count:
                # 快速重试阶段
                delay_s = policy.quick_retry_ms / 1000.0
                phase = "quick"
            else:
                # 慢速重试 + 抖动
                delay_s = compute_slow_delay_s(policy.slow_retry_ms, policy.jitter_pct)
                phase = "slow"

            if delay_s > 0:
                await asyncio.sleep(delay_s)

            try:
                order = await api.run_preview_check_chain()
                latency = (time.perf_counter() - t0) * 1000
                log.success(
                    f"[{name}] 抢购成功(第{attempt}次 {phase} 阶段)! "
                    f"orderId={order.order_id} bizId={order.biz_id[:8]}... "
                    f"耗时 {latency:.0f}ms"
                )
                return AccountResult(
                    account_name=name,
                    success=True,
                    order=order,
                    latency_ms=latency,
                )
            except (AuthError, RiskBlockedError) as e:
                latency = (time.perf_counter() - t0) * 1000
                log.error(f"[{name}] {type(e).__name__}: {e}")
                return _fail(session, e, type(e).__name__, latency)
            except SoldOutError as e:
                # 售罄——是真没了还是瞬时?这里选择不重试(避免给服务器压力)
                latency = (time.perf_counter() - t0) * 1000
                log.warning(
                    f"[{name}] 售罄(第{attempt}次): {e}"
                )
                return _fail(session, e, "SoldOutError", latency)
            except (CheckExpireError, NetworkError, RateLimitedError) as e:
                # 这些是可重试错误,继续循环
                last_error = e
                log.debug(
                    f"[{name}] 第{attempt}次 {phase} {type(e).__name__}: {e},"
                    f"下次延迟 {delay_s * 1000:.0f}ms"
                )
                continue
            except ZhipuError as e:
                # 其他业务错误,短暂重试
                last_error = e
                log.debug(
                    f"[{name}] 第{attempt}次 {phase} 业务错误: {e}"
                )
                continue
            except Exception as e:  # noqa: BLE001
                latency = (time.perf_counter() - t0) * 1000
                log.exception(f"[{name}] 未预期异常")
                return _fail(session, e, "Unexpected", latency)

        # 达到 max_total_attempts 都没成功
        latency = (time.perf_counter() - t0) * 1000
        if last_error:
            log.error(
                f"[{name}] 自适应重试耗尽({attempt}/{policy.max_total_attempts}次, "
                f"最后错误: {last_error})"
            )
            return _fail(session, last_error, type(last_error).__name__, latency)
        log.error(
            f"[{name}] 自适应重试耗尽({attempt}/{policy.max_total_attempts}次) 无错误记录"
        )
        return _fail(
            session, RuntimeError("重试耗尽"), "MaxRetriesReached", latency,
        )


def compute_slow_delay_s(base_ms: int, jitter_pct: float) -> float:
    """计算慢速重试阶段的延迟(秒)。

    公式: ``delay = base + uniform(-jitter, +jitter)``,
    其中 ``jitter = base * jitter_pct``。

    Args:
        base_ms: 基础间隔毫秒(slow_retry_ms)。
        jitter_pct: 抖动比例 0~1,jitter_pct=0.3 表示 ±30%。

    Returns:
        延迟秒数。

    Examples:
        >>> compute_slow_delay_s(100, 0.3)
        0.07   # 介于 70ms~130ms 之间的某个值
    """
    base = base_ms / 1000.0
    if jitter_pct <= 0.0:
        return base
    jitter = base * jitter_pct
    return base + random.uniform(-jitter, jitter)


def _fail(
    session: Session, e: Exception, error_type: str, latency_ms: float
) -> AccountResult:
    return AccountResult(
        account_name=session.account.name,
        success=False,
        error=str(e),
        error_type=error_type,
        latency_ms=latency_ms,
    )
