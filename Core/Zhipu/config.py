"""配置加载与校验模块.

使用 pydantic 对 YAML 配置进行强类型校验，给出清晰的错误提示。
同时负责把明文配置里的账号凭证落地为加密存储。
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# 枚举与常量
# ---------------------------------------------------------------------------


class Plan(str, Enum):
    """支持的套餐档位。"""

    LITE = "Lite"
    PRO = "Pro"
    MAX = "Max"


class BillingCycle(str, Enum):
    """计费周期。"""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class PayChannel(str, Enum):
    """支付渠道。"""

    ALIPAY = "alipay"
    WECHAT_PAY = "weChat_pay"
    BALANCE_PAY = "balance_pay"
    PUBLIC_PAY = "public_pay"


class NotifyType(str, Enum):
    """通知渠道。"""

    WECHAT = "wechat"
    DINGTALK = "dingtalk"
    TELEGRAM = "telegram"
    SOUND = "sound"
    NONE = "none"


# ---------------------------------------------------------------------------
# 子模型
# ---------------------------------------------------------------------------


class Account(BaseModel):
    """单个账号配置。"""

    name: str = Field(..., description="账号别名，用于日志区分")
    cookie: Optional[str] = Field(None, description="登录 Cookie 字符串")
    token: Optional[str] = Field(None, description="Bearer Token（与 Cookie 二选一）")
    phone: Optional[str] = Field(None, description="手机号，用于短信验证码登录")
    enabled: bool = Field(True, description="是否参与本次抢购")

    model_config = ConfigDict(extra="ignore")


class PlanGroup(BaseModel):
    """一组独立的抢购配置。同一账号可以同时跑多组(并发)。

    字段语义与原 AppConfig 单套餐字段一一对应,但聚合成一条独立的
    抢购链路 —— 适合"Max/年/支付宝" + "Lite/月/微信"这种多组并抢场景。

    必填字段:name(用于日志区分) + target_plan + billing_cycle + pay_channel。
    """

    name: str = Field(default="默认", description="组名,仅用于日志/UI 区分")
    target_plan: Plan = Field(default=Plan.PRO, description="目标套餐档位")
    billing_cycle: BillingCycle = Field(
        default=BillingCycle.YEARLY, description="计费周期"
    )
    pay_channel: PayChannel = Field(
        default=PayChannel.ALIPAY, description="支付渠道"
    )
    use_pinhaomo: bool = Field(default=True, description="是否使用拼好模")
    product_id: Optional[str] = Field(
        default=None, description="指定 productId;为空时走 batch-preview 兜底"
    )
    enabled: bool = Field(default=True, description="本组是否参与本次抢购")
    fallback_within_group: list[Plan] = Field(
        default_factory=list,
        description="组内降级顺序(高→低);为空=不降级",
    )
    notes: str = Field(default="", description="备注,描述这组配置的用途")

    model_config = ConfigDict(extra="ignore")

    @field_validator("fallback_within_group")
    @classmethod
    def _no_self_fallback(cls, v: list[Plan], info) -> list[Plan]:
        # info.data 含同实例其他字段(仅在 v2 可用;若退化再额外 model_validator 兜底)
        target = info.data.get("target_plan")
        if target and target in v:
            raise ValueError(
                f"fallback_within_group 不能包含 target_plan={target}"
            )
        # 去重保序
        seen: set[Plan] = set()
        out: list[Plan] = []
        for p in v:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out


class Notification(BaseModel):
    type: NotifyType = NotifyType.NONE
    webhook: Optional[str] = None
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    sound_on_success: bool = True

    model_config = ConfigDict(extra="ignore")


class RetryPolicy(BaseModel):
    times: int = Field(3, ge=0, le=10, description="最大重试次数")
    delay_ms: int = Field(500, ge=0, description="初始重试延迟（毫秒）")
    backoff_factor: float = Field(2.0, ge=1.0, description="指数退避因子")
    on_429_wait_ms: int = Field(2000, ge=0, description="命中限流时的额外等待")


class AdaptiveRetryPolicy(BaseModel):
    """qtaxm/glm-rush 风格的自适应重试策略。

    时间线::
        第 1..burst_count 次: 零延迟爆发 (前 N 次争抢首批配额)
        第 burst_count+1..quick_count 次: quick_retry_ms 间隔 (默认 30ms)
        之后: slow_retry_ms ± jitter_pct 抖动 (默认 100ms ± 30%)

    这样能在前 0.1 秒发出最多 burst_count + quick_count 个请求,最大化抢到首批配额概率;
    后续请求逐步放慢避免被风控。
    """
    burst_count: int = Field(20, ge=0, le=100, description="零延迟爆发次数")
    quick_count: int = Field(10, ge=0, le=50, description="快速重试次数")
    quick_retry_ms: int = Field(30, ge=0, description="快速重试间隔 ms")
    slow_retry_ms: int = Field(100, ge=0, description="慢速重试基础间隔 ms")
    jitter_pct: float = Field(0.3, ge=0.0, le=1.0, description="± 抖动百分比")
    max_total_attempts: int = Field(60, ge=1, le=500, description="硬上限防止无限循环")
    use_preview_check_mode: bool = Field(
        True, description="True=qtaxm 模式(preview+check+EXPIRE 重试), False=原 batch-preview 模式"
    )


# ---------------------------------------------------------------------------
# 主配置
# ---------------------------------------------------------------------------


class AppConfig(BaseModel):
    """抢购脚本主配置。"""

    # 目标
    target_plan: Plan = Plan.PRO
    # 优先抢购套餐列表（从高到低）：抢购时按顺序找第一个非售罄的套餐下单。
    # 不配置时自动用 [target_plan] 单元素列表，向后兼容。
    target_plans: list[Plan] = Field(default_factory=list)
    billing_cycle: BillingCycle = BillingCycle.YEARLY
    use_pinhaomo: bool = True
    pay_channel: PayChannel = PayChannel.ALIPAY

    # 账号
    accounts: list[Account] = Field(default_factory=list)

    # 定时
    target_time: str = Field(
        "2026-06-18 10:00:00",
        description="目标开抢时间，格式 YYYY-MM-DD HH:MM:SS",
    )
    time_offset_ms: int = Field(
        -3000,
        description="相对目标时间提前多少毫秒发起请求（负值=提前）",
    )
    ntp_server: str = "ntp.aliyun.com"
    ntp_sync_times: int = Field(3, ge=1, description="NTP 同步取多次平均")
    ntp_max_drift_ms: int = Field(
        50, ge=0, description="可接受的最大时钟漂移（毫秒），超出则告警"
    )
    preheat_seconds: float = Field(5.0, ge=0, description="提前多少秒预热连接")

    # 并发
    max_concurrent: int = Field(3, ge=1, le=20)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    adaptive_retry: AdaptiveRetryPolicy = Field(default_factory=AdaptiveRetryPolicy)

    # 通知
    notification: Notification = Field(default_factory=Notification)

    # 网络
    proxy: Optional[str] = None
    request_timeout_s: float = Field(10.0, gt=0)

    # 安全
    secret_store: str = Field(
        ".secrets.enc",
        description="加密凭证存储文件路径（相对工作目录）",
    )

    # 备选浏览器方案
    browser_mode: bool = False
    headless: bool = False

    # ===== 多套餐配置(v5.x) =====
    # 每个组是一组独立的抢购配置(target_plan + billing_cycle + pay_channel + pinhaomo)。
    # 留空时,启动时自动从上面的 target_plan / billing_cycle / pay_channel / use_pinhaomo
    # 折叠成 1 个默认组 —— 保持向后兼容。
    plan_groups: list[PlanGroup] = Field(
        default_factory=list,
        description="多套餐配置列表;为空则自动从单套餐字段折叠成单组",
    )

    model_config = ConfigDict(extra="ignore")

    # -- 校验 ---------------------------------------------------------------

    @field_validator("accounts")
    @classmethod
    def _check_accounts(cls, v: list[Account]) -> list[Account]:
        if not v:
            raise ValueError("至少需要配置一个账号")
        enabled = [a for a in v if a.enabled]
        if not enabled:
            raise ValueError("至少需要一个 enabled=True 的账号")
        return v

    @model_validator(mode="after")
    def _check_notification_deps(self) -> "AppConfig":
        # target_plans 为空时，用 [target_plan] 兜底，向后兼容单套餐配置
        if not self.target_plans:
            self.target_plans = [self.target_plan]
        # 去重（保序）
        seen: set[Plan] = set()
        deduped: list[Plan] = []
        for p in self.target_plans:
            if p not in seen:
                seen.add(p)
                deduped.append(p)
        self.target_plans = deduped

        n = self.notification
        if n.type == NotifyType.WECHAT and not n.webhook:
            raise ValueError("通知类型为 wechat 时必须配置 notification.webhook")
        if n.type == NotifyType.DINGTALK and not n.webhook:
            raise ValueError("通知类型为 dingtalk 时必须配置 notification.webhook")
        if n.type == NotifyType.TELEGRAM and not (
            n.telegram_token and n.telegram_chat_id
        ):
            raise ValueError(
                "通知类型为 telegram 时必须配置 telegram_token 和 telegram_chat_id"
            )

        # ===== 多套餐配置折叠 =====
        # 向后兼容:plan_groups 为空时,自动从单套餐字段折叠成 1 个默认组。
        # 同时把 target_plans[1:] 作为默认组的 fallback_within_group(剔除 self)。
        if not self.plan_groups:
            fallback = [p for p in self.target_plans[1:] if p != self.target_plan]
            self.plan_groups = [
                PlanGroup(
                    name="默认",
                    target_plan=self.target_plan,
                    billing_cycle=self.billing_cycle,
                    pay_channel=self.pay_channel,
                    use_pinhaomo=self.use_pinhaomo,
                    fallback_within_group=fallback,
                )
            ]
        else:
            # 同实例内多组:校验 enabled=True 的组名不重复(空名视为合法但允许)
            seen: set[str] = set()
            for i, g in enumerate(self.plan_groups):
                if not g.enabled:
                    continue
                key = (g.name or f"#{i}")
                if key in seen:
                    raise ValueError(
                        f"plan_groups 中存在重复的组名: {g.name!r} (索引 {i})"
                    )
                seen.add(key)

        # 只保留 enabled=True 的组
        self.plan_groups = [g for g in self.plan_groups if g.enabled]

        return self

    # -- 便捷属性 -----------------------------------------------------------

    @property
    def enabled_accounts(self) -> list[Account]:
        return [a for a in self.accounts if a.enabled]

    @property
    def enabled_plan_groups(self) -> list[PlanGroup]:
        # model_validator 已经过滤过 enabled=False 的组,这里再过滤一次兜底
        return [g for g in self.plan_groups if g.enabled]


# ---------------------------------------------------------------------------
# 加载入口
# ---------------------------------------------------------------------------


_CONFIG: Optional[AppConfig] = None


def load_config(path: str | os.PathLike[str], *, reload: bool = False) -> AppConfig:
    """从 YAML 文件加载并校验配置。

    Args:
        path: YAML 配置文件路径。
        reload: 是否强制重新读取（忽略缓存）。

    Returns:
        校验后的 :class:`AppConfig` 实例。
    """
    global _CONFIG
    if _CONFIG is not None and not reload:
        return _CONFIG

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在: {p}")

    with p.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    try:
        cfg = AppConfig(**raw)
    except Exception as e:  # noqa: BLE001
        # 把 pydantic 的错误信息抛给调用方，便于在 CLI 层打印
        raise RuntimeError(f"配置校验失败:\n{e}") from e

    _CONFIG = cfg
    return cfg


def get_config() -> AppConfig:
    """获取已加载的配置；若未加载则抛错。"""
    if _CONFIG is None:
        raise RuntimeError("配置尚未加载，请先调用 load_config()")
    return _CONFIG
