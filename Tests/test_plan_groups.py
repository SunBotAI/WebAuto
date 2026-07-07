"""Tests for multi plan-group configuration.

覆盖范围:
- PlanGroup 子模型校验(target / fallback / 重复名 / 去重)
- AppConfig 后向兼容(老字段折叠成 1 个默认组)
- AppConfig 多组显式声明 + 校验失败路径
- PlanGroupScheduler 临时 cfg 派生(只覆盖 6 字段,其余继承)
- PlanGroupScheduler.run 串/并混合下结果分组(group 字段填充)
- pick_best_available / run_preview_check_chain 在新结构下行为不变
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from Core.Zhipu.config import (
    Account,
    AppConfig,
    BillingCycle,
    PayChannel,
    Plan,
    PlanGroup,
)
from Core.Zhipu.group_scheduler import PlanGroupScheduler, _build_group_config
from Core.Zhipu.scheduler import AccountResult, GrabScheduler, GrabSummary
from Core.Zhipu.timesync import TimeSync


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _acc(name: str = "acc1") -> Account:
    return Account(name=name, phone="13800000000", enabled=True)


def _cfg(**overrides) -> AppConfig:
    base = dict(accounts=[_acc()])
    base.update(overrides)
    return AppConfig(**base)


# ---------------------------------------------------------------------------
# 1. back-compat: 老字段折叠成 1 个默认组
# ---------------------------------------------------------------------------


def test_back_compat_folds_single_group():
    """没显式给 plan_groups 时,自动从单套餐字段折叠成 1 个默认组。"""
    cfg = _cfg(
        target_plan=Plan.MAX,
        target_plans=[Plan.MAX, Plan.PRO],
        billing_cycle=BillingCycle.YEARLY,
        pay_channel=PayChannel.ALIPAY,
        use_pinhaomo=False,
    )
    assert len(cfg.enabled_plan_groups) == 1
    g = cfg.enabled_plan_groups[0]
    assert g.name == "默认"
    assert g.target_plan == Plan.MAX
    assert g.billing_cycle == BillingCycle.YEARLY
    assert g.pay_channel == PayChannel.ALIPAY
    assert g.use_pinhaomo is False
    # 老的 target_plans[1:] 进 fallback_within_group
    assert g.fallback_within_group == [Plan.PRO]


# ---------------------------------------------------------------------------
# 2. 多组显式声明 + 后向兼容 target_plans 不参与新组
# ---------------------------------------------------------------------------


def test_multi_groups_explicit_passthrough():
    """plan_groups 显式给定时,自动从单套餐字段折叠关闭(仅看显式声明)。"""
    cfg = _cfg(
        plan_groups=[
            PlanGroup(name="A组", target_plan=Plan.MAX, billing_cycle=BillingCycle.YEARLY),
            PlanGroup(name="B组", target_plan=Plan.LITE, billing_cycle=BillingCycle.MONTHLY, pay_channel=PayChannel.BALANCE_PAY),
        ]
    )
    assert len(cfg.enabled_plan_groups) == 2
    assert cfg.enabled_plan_groups[0].name == "A组"
    assert cfg.enabled_plan_groups[1].target_plan == Plan.LITE
    assert cfg.enabled_plan_groups[1].pay_channel == PayChannel.BALANCE_PAY


# ---------------------------------------------------------------------------
# 3. 重复组名校验失败
# ---------------------------------------------------------------------------


def test_duplicate_group_name_rejected():
    with pytest.raises(Exception) as exc:
        AppConfig(
            accounts=[_acc()],
            plan_groups=[
                PlanGroup(name="dup", target_plan=Plan.MAX),
                PlanGroup(name="dup", target_plan=Plan.LITE),
            ],
        )
    assert "重复" in str(exc.value)


# ---------------------------------------------------------------------------
# 4. fallback 包含 self 校验失败
# ---------------------------------------------------------------------------


def test_self_in_fallback_rejected():
    with pytest.raises(Exception) as exc:
        PlanGroup(
            name="x",
            target_plan=Plan.MAX,
            fallback_within_group=[Plan.MAX, Plan.PRO],
        )
    assert "fallback_within_group" in str(exc.value) or "target_plan" in str(exc.value)


# ---------------------------------------------------------------------------
# 5. fallback 自动去重保序
# ---------------------------------------------------------------------------


def test_fallback_dedup_preserves_order():
    g = PlanGroup(
        name="x",
        target_plan=Plan.MAX,
        fallback_within_group=[Plan.PRO, Plan.PRO, Plan.LITE],
    )
    assert g.fallback_within_group == [Plan.PRO, Plan.LITE]


# ---------------------------------------------------------------------------
# 6. enabled=False 的组被过滤
# ---------------------------------------------------------------------------


def test_disabled_group_filtered():
    cfg = _cfg(
        plan_groups=[
            PlanGroup(name="A", target_plan=Plan.MAX, enabled=True),
            PlanGroup(name="B", target_plan=Plan.LITE, enabled=False),
        ]
    )
    names = [g.name for g in cfg.enabled_plan_groups]
    assert names == ["A"]


# ---------------------------------------------------------------------------
# 7. _build_group_config 只覆盖 6 字段
# ---------------------------------------------------------------------------


def test_build_group_config_overrides_only_six_fields():
    base = _cfg(
        target_time="2099-01-01 10:00:00",
        ntp_server="ntp.aliyun.com",
        max_concurrent=3,
        preheat_seconds=7.0,
        target_plan=Plan.MAX,
        billing_cycle=BillingCycle.YEARLY,
        pay_channel=PayChannel.ALIPAY,
        use_pinhaomo=True,
        proxy="http://base-proxy",
        request_timeout_s=12.0,
    )
    group = PlanGroup(
        name="G1",
        target_plan=Plan.LITE,
        billing_cycle=BillingCycle.MONTHLY,
        pay_channel=PayChannel.BALANCE_PAY,
        use_pinhaomo=False,
    )
    derived = _build_group_config(base, group)
    # 覆盖项
    assert derived.target_plan == Plan.LITE
    assert derived.billing_cycle == BillingCycle.MONTHLY
    assert derived.pay_channel == PayChannel.BALANCE_PAY
    assert derived.use_pinhaomo is False
    # target_plans 折叠 = [group.target_plan] + fallback
    assert derived.target_plans == [Plan.LITE]
    # 保留项
    assert derived.target_time == base.target_time
    assert derived.ntp_server == base.ntp_server
    assert derived.max_concurrent == 3
    assert derived.preheat_seconds == 7.0
    assert derived.proxy == "http://base-proxy"
    assert derived.request_timeout_s == 12.0
    # 不动 plan_groups(model_validator 已经折叠过,这里只覆盖 6 字段)
    # base 的 plan_groups 经过 model_validator 已经是 1 个默认组;派生应该被 base.model_copy 透传(不是 None)
    # 注意:_build_group_config 不在 derived 上跑 model_validator,所以 derived.plan_groups 可能仍为空列表
    # 这是允许的——GrabScheduler 只读 target_plan/target_plans/billing_cycle/pay_channel/use_pinhaomo


# ---------------------------------------------------------------------------
# 8. PlanGroupScheduler.run 把每组 AccountResult 标上 group 字段
# ---------------------------------------------------------------------------


def test_plan_group_scheduler_tags_results():
    """mock GrabScheduler.run 返回带 account_name 的 results,
    PlanGroupScheduler 应把每个 result 的 group 字段填上组名。"""

    async def main():
        # 两个组,共享 1 个 session
        cfg = _cfg(
            plan_groups=[
                PlanGroup(name="A组", target_plan=Plan.MAX),
                PlanGroup(name="B组", target_plan=Plan.LITE),
            ]
        )
        ts = TimeSync(offset_s=0.0)

        # mock session
        fake_session = MagicMock()
        fake_session.account.name = "acc1"
        fake_session.aclose = AsyncMock()

        # mock GrabScheduler
        sched = PlanGroupScheduler(cfg, ts)
        call_count = {"n": 0}

        async def fake_run(group, sessions, *, dry_run=False):
            call_count["n"] += 1
            return GrabSummary(results=[
                AccountResult(account_name="acc1", success=True, latency_ms=10.0)
            ])

        sched._run_one_group = AsyncMock(side_effect=fake_run)

        summary = await sched.run([fake_session])
        # 两个组都跑了
        assert call_count["n"] == 2
        # 结果合并:每组各贡献 1 条 result,共 2 条
        assert len(summary.results) == 2
        groups = {r.group for r in summary.results}
        assert groups == {"A组", "B组"}
        # 每条都标了来源组
        for r in summary.results:
            assert r.group in ("A组", "B组")
            assert r.success is True

        # 清理 mock aclose
        await fake_session.aclose()

    asyncio.run(main())


# ---------------------------------------------------------------------------
# 9. PlanGroupScheduler.run 在某组异常时不会拖垮其它组
# ---------------------------------------------------------------------------


def test_plan_group_scheduler_isolates_group_exceptions():
    async def main():
        cfg = _cfg(
            plan_groups=[
                PlanGroup(name="OK", target_plan=Plan.MAX),
                PlanGroup(name="FAIL", target_plan=Plan.LITE),
            ]
        )
        ts = TimeSync(offset_s=0.0)
        fake_session = MagicMock()
        fake_session.account.name = "acc1"
        fake_session.aclose = AsyncMock()

        sched = PlanGroupScheduler(cfg, ts)

        async def ok_run(group, sessions, *, dry_run=False):
            return GrabSummary(results=[AccountResult(account_name="acc1", success=True)])

        async def fail_run(group, sessions, *, dry_run=False):
            raise RuntimeError("boom")

        async def dispatch(group, sessions, *, dry_run=False):
            return await (ok_run if group.name == "OK" else fail_run)(group, sessions, dry_run=dry_run)

        sched._run_one_group = AsyncMock(side_effect=dispatch)
        summary = await sched.run([fake_session])

        # 2 条 result:OK 组成功,FAIL 组整组失败
        assert len(summary.results) == 2
        by_group = {r.group: r for r in summary.results}
        assert by_group["OK"].success is True
        assert by_group["FAIL"].success is False
        assert "boom" in (by_group["FAIL"].error or "")
        assert by_group["FAIL"].error_type == "GroupSchedulerError"
        await fake_session.aclose()

    asyncio.run(main())


# ---------------------------------------------------------------------------
# 10. PlanGroupScheduler 在无组时返回空 results(不抛)
# ---------------------------------------------------------------------------


def test_plan_group_scheduler_empty_groups():
    async def main():
        cfg = AppConfig(
            accounts=[_acc()],
            plan_groups=[],  # 显式空 → model_validator 折叠成 1 个默认组
        )
        # 验证折叠
        assert len(cfg.enabled_plan_groups) == 1

        # 如果运行时人为塞空列表进来,scheduler 应不崩
        cfg_empty = cfg.model_copy(update={"plan_groups": []})
        # 此时不跑 model_validator;enabled_plan_groups 返回 []
        assert cfg_empty.enabled_plan_groups == []

        fake_session = MagicMock()
        fake_session.account.name = "acc1"
        fake_session.aclose = AsyncMock()

        ts = TimeSync(offset_s=0.0)
        sched = PlanGroupScheduler(cfg_empty, ts)
        summary = await sched.run([fake_session])
        # 每账号 1 条 EmptyGroups 失败
        assert len(summary.results) == 1
        assert summary.results[0].error_type == "EmptyGroups"
        await fake_session.aclose()

    asyncio.run(main())


# ---------------------------------------------------------------------------
# 11. PlanGroupScheduler 在无 session 时返回空 results
# ---------------------------------------------------------------------------


def test_plan_group_scheduler_no_sessions():
    async def main():
        cfg = _cfg(plan_groups=[PlanGroup(name="X", target_plan=Plan.MAX)])
        ts = TimeSync(offset_s=0.0)
        sched = PlanGroupScheduler(cfg, ts)
        summary = await sched.run([])
        assert summary.results == []

    asyncio.run(main())


# ---------------------------------------------------------------------------
# 12. _build_group_config 把 fallback 接到 target_plans 头部
# ---------------------------------------------------------------------------


def test_build_group_config_target_plans_order():
    base = _cfg(target_plans=[Plan.MAX, Plan.PRO])
    group = PlanGroup(
        name="G",
        target_plan=Plan.LITE,
        fallback_within_group=[Plan.PRO, Plan.MAX],
    )
    derived = _build_group_config(base, group)
    # target_plans 应该是 [group.target_plan] + fallback_within_group
    assert derived.target_plans == [Plan.LITE, Plan.PRO, Plan.MAX]


# ---------------------------------------------------------------------------
# 13. PlanGroup 可选字段默认值
# ---------------------------------------------------------------------------


def test_plan_group_defaults():
    g = PlanGroup(name="g")
    assert g.target_plan == Plan.PRO
    assert g.billing_cycle == BillingCycle.YEARLY
    assert g.pay_channel == PayChannel.ALIPAY
    assert g.use_pinhaomo is True
    assert g.product_id is None
    assert g.enabled is True
    assert g.fallback_within_group == []
    assert g.notes == ""


# ---------------------------------------------------------------------------
# 14. yaml 多组加载端到端(模拟 yaml.safe_load)
# ---------------------------------------------------------------------------


def test_yaml_multi_groups_load():
    """从 yaml dict 加载 AppConfig,验证多组结构。"""
    raw = {
        "accounts": [{"name": "a"}],
        "plan_groups": [
            {
                "name": "Max年付",
                "target_plan": "Max",
                "billing_cycle": "yearly",
                "pay_channel": "alipay",
            },
            {
                "name": "Lite月付",
                "target_plan": "Lite",
                "billing_cycle": "monthly",
                "pay_channel": "balance_pay",
                "use_pinhaomo": False,
            },
        ],
    }
    cfg = AppConfig(**raw)
    assert len(cfg.enabled_plan_groups) == 2
    assert cfg.enabled_plan_groups[0].name == "Max年付"
    assert cfg.enabled_plan_groups[0].target_plan == Plan.MAX
    assert cfg.enabled_plan_groups[1].use_pinhaomo is False


# ---------------------------------------------------------------------------
# 15. yaml 老格式不带 plan_groups(向后兼容)
# ---------------------------------------------------------------------------


def test_yaml_old_format_still_works():
    raw = {
        "accounts": [{"name": "a"}],
        "target_plan": "Max",
        "target_plans": ["Max", "Pro"],
        "billing_cycle": "yearly",
        "pay_channel": "alipay",
    }
    cfg = AppConfig(**raw)
    # 自动折叠成 1 个默认组
    assert len(cfg.enabled_plan_groups) == 1
    assert cfg.enabled_plan_groups[0].target_plan == Plan.MAX
    assert cfg.enabled_plan_groups[0].fallback_within_group == [Plan.PRO]