"""Scheduler 自适应重试单测.

覆盖 qtaxm/glm-rush 风格的自适应重试策略:
- 零延迟爆发 → quick 阶段 → slow 阶段 的延迟计算
- 成功立即返回
- SoldOutError 立即退出(不重试)
- CheckExpireError / NetworkError 继续重试
- max_total_attempts 兜底退出
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from Core.Zhipu.scheduler import GrabScheduler, AccountResult
from Core.Zhipu.session import Session
from Core.Zhipu.config import (
    AppConfig, Account, AdaptiveRetryPolicy, Plan, BillingCycle,
)
from Core.Zhipu.exceptions import (
    SoldOutError, CheckExpireError, NetworkError, AuthError,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_cfg(**adaptive_overrides):
    """构造一个带自定义 adaptive_retry 的 cfg。"""
    cfg = AppConfig(
        accounts=[Account(name='test', phone='13800000000')],
        target_plan='Max',
        target_plans=[Plan.MAX],
        billing_cycle='yearly',
        pay_channel='alipay',
    )
    # 默认参数
    defaults = dict(
        burst_count=2,
        quick_count=2,
        quick_retry_ms=10,
        slow_retry_ms=20,
        jitter_pct=0.0,
        max_total_attempts=5,
    )
    defaults.update(adaptive_overrides)
    cfg.adaptive_retry = AdaptiveRetryPolicy(**defaults)
    return cfg


class AdaptiveRetryTest(unittest.TestCase):
    """测试 _grab_with_adaptive_retry 的关键行为。"""

    def _make_session(self, name='test'):
        # 构造最小 Session:client 不需要真实 API
        sess = Session.__new__(Session)
        sess.account = Account(name=name, phone='13800000000')
        sess.client = MagicMock()
        sess.client.aclose = AsyncMock()
        return sess

    def test_success_on_first_attempt_returns_immediately(self):
        cfg = _make_cfg()
        sched = GrabScheduler(cfg, MagicMock())
        sess = self._make_session()

        # mock api.run_preview_check_chain 直接返回成功
        fake_order = MagicMock()
        fake_order.order_id = "ORD-1"
        fake_order.biz_id = "biz-abc-12345"
        async def fake_success():
            return fake_order

        async def go():
            # 直接调真实 _grab_with_adaptive_retry
            from Core.Zhipu.api import BigModelApi
            api = BigModelApi(sess.client, cfg)
            api.run_preview_check_chain = fake_success
            return await sched._grab_with_adaptive_retry(sess, api, 0.0)

        result = run(go())
        self.assertTrue(result.success)
        self.assertEqual(result.order.order_id, "ORD-1")

    def test_sold_out_exits_immediately_no_retry(self):
        """SoldOutError 不应该被重试(避免给服务器打爆)。"""
        cfg = _make_cfg()
        sched = GrabScheduler(cfg, MagicMock())
        sess = self._make_session()

        calls = [0]
        async def fake_sold_out():
            calls[0] += 1
            raise SoldOutError("mock sold out")

        async def go():
            from Core.Zhipu.api import BigModelApi
            api = BigModelApi(sess.client, cfg)
            api.run_preview_check_chain = fake_sold_out
            return await sched._grab_with_adaptive_retry(sess, api, 0.0)

        result = run(go())
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "SoldOutError")
        self.assertEqual(calls[0], 1)   # 只调用一次就退出

    def test_check_expire_retries_until_success(self):
        """CheckExpireError 是可重试的,重试直到成功。"""
        cfg = _make_cfg(max_total_attempts=5)
        sched = GrabScheduler(cfg, MagicMock())
        sess = self._make_session()

        calls = [0]
        fake_order = MagicMock()
        fake_order.order_id = "ORD-2"
        fake_order.biz_id = "biz-final"
        async def fake_run():
            calls[0] += 1
            if calls[0] < 3:
                raise CheckExpireError(f"mock expire #{calls[0]}")
            return fake_order

        async def go():
            from Core.Zhipu.api import BigModelApi
            api = BigModelApi(sess.client, cfg)
            api.run_preview_check_chain = fake_run
            return await sched._grab_with_adaptive_retry(sess, api, 0.0)

        result = run(go())
        self.assertTrue(result.success)
        self.assertEqual(calls[0], 3)
        self.assertEqual(result.order.order_id, "ORD-2")

    def test_max_attempts_returns_failure(self):
        """达到 max_total_attempts 仍然失败 → 返回失败结果。"""
        cfg = _make_cfg(max_total_attempts=3)
        sched = GrabScheduler(cfg, MagicMock())
        sess = self._make_session()

        calls = [0]
        async def fake_always_expire():
            calls[0] += 1
            raise CheckExpireError(f"expire #{calls[0]}")

        async def go():
            from Core.Zhipu.api import BigModelApi
            api = BigModelApi(sess.client, cfg)
            api.run_preview_check_chain = fake_always_expire
            return await sched._grab_with_adaptive_retry(sess, api, 0.0)

        result = run(go())
        self.assertFalse(result.success)
        self.assertEqual(calls[0], 3)
        self.assertEqual(result.error_type, "CheckExpireError")

    def test_auth_error_exits_immediately(self):
        """AuthError 不重试(无意义)。"""
        cfg = _make_cfg()
        sched = GrabScheduler(cfg, MagicMock())
        sess = self._make_session()

        calls = [0]
        async def fake_auth_fail():
            calls[0] += 1
            raise AuthError("token expired")

        async def go():
            from Core.Zhipu.api import BigModelApi
            api = BigModelApi(sess.client, cfg)
            api.run_preview_check_chain = fake_auth_fail
            return await sched._grab_with_adaptive_retry(sess, api, 0.0)

        result = run(go())
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "AuthError")
        self.assertEqual(calls[0], 1)


class AdaptivePolicyTest(unittest.TestCase):
    """AdaptiveRetryPolicy 配置测试。"""

    def test_defaults(self):
        p = AdaptiveRetryPolicy()
        self.assertEqual(p.burst_count, 20)
        self.assertEqual(p.quick_count, 10)
        self.assertEqual(p.quick_retry_ms, 30)
        self.assertEqual(p.slow_retry_ms, 100)
        self.assertEqual(p.jitter_pct, 0.3)
        self.assertEqual(p.max_total_attempts, 60)
        self.assertTrue(p.use_preview_check_mode)

    def test_in_appconfig(self):
        cfg = AppConfig(
            accounts=[Account(name='t', phone='13800000000')],
            target_plan='Max',
            billing_cycle='yearly',
            pay_channel='alipay',
        )
        self.assertTrue(cfg.adaptive_retry.use_preview_check_mode)
        # 可以覆写
        cfg.adaptive_retry.burst_count = 5
        self.assertEqual(cfg.adaptive_retry.burst_count, 5)


class ComputeSlowDelaySTest(unittest.TestCase):
    """compute_slow_delay_s 纯函数测试,验证 jitter 上下界。"""

    def test_no_jitter_returns_base(self):
        from Core.Zhipu.scheduler import compute_slow_delay_s
        # jitter_pct=0 → 严格返回 base
        self.assertAlmostEqual(compute_slow_delay_s(100, 0.0), 0.1, places=6)
        self.assertAlmostEqual(compute_slow_delay_s(50, 0.0), 0.05, places=6)

    def test_jitter_within_bounds(self):
        """jitter_pct=0.3 时,结果应在 base*(1-0.3) ~ base*(1+0.3) 之间。"""
        from Core.Zhipu.scheduler import compute_slow_delay_s
        base_ms = 100
        for _ in range(200):  # 多采样避免随机侥幸
            d = compute_slow_delay_s(base_ms, 0.3)
            self.assertGreaterEqual(d, 0.07, f"lower bound violation: {d}")
            self.assertLessEqual(d, 0.13, f"upper bound violation: {d}")

    def test_zero_base_returns_zero(self):
        from Core.Zhipu.scheduler import compute_slow_delay_s
        # base=0 抖动用 0 也不应该出问题
        self.assertAlmostEqual(compute_slow_delay_s(0, 0.5), 0.0, places=6)
        self.assertAlmostEqual(compute_slow_delay_s(0, 0.0), 0.0, places=6)

    def test_full_jitter(self):
        """jitter_pct=1.0 时,应在 [0, 2*base] 范围内。"""
        from Core.Zhipu.scheduler import compute_slow_delay_s
        for _ in range(200):
            d = compute_slow_delay_s(100, 1.0)
            self.assertGreaterEqual(d, 0.0)
            self.assertLessEqual(d, 0.2)

    def test_negative_jitter_treated_as_zero(self):
        """jitter_pct < 0 应被当作 0(jitter 不能为负)。"""
        from Core.Zhipu.scheduler import compute_slow_delay_s
        self.assertAlmostEqual(compute_slow_delay_s(100, -0.5), 0.1, places=6)


class SchedulerDryRunTest(unittest.TestCase):
    """Scheduler.run(dry_run=True) 测试:不实际下单,只走时序。"""

    def _make_sessions(self, n=3):
        """构造 n 个 mock Session。"""
        sessions = []
        for i in range(n):
            sess = Session.__new__(Session)
            sess.account = Account(name=f"acc-{i}", phone=f"1380000000{i}")
            sess.client = MagicMock()
            sess.client.preheat = AsyncMock()
            sess.user_id = f"user-{i}"
            sessions.append(sess)
        return sessions

    def test_dry_run_skips_actual_grab(self):
        """dry_run=True:不调 _grab_one,所有结果 DryRun 标记。"""
        from Core.Zhipu.scheduler import GrabScheduler
        from Core.Zhipu.timesync import TimeSync
        from datetime import datetime, timedelta

        cfg = AppConfig(
            accounts=[Account(name='t', phone='13800000000')],
            target_plan='Max',
            billing_cycle='yearly',
            pay_channel='alipay',
            preheat_seconds=1,
            max_concurrent=4,
        )
        # target_time 用 scheduler 支持的 "%Y-%m-%d %H:%M:%S" 格式
        # 设成 3 秒后,让 dry-run 能完整跑过预热等待但不会等太久
        cfg.target_time = (datetime.now() + timedelta(seconds=3)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        # offset_s=0.0 表示本地时钟 = 服务器时钟;为防止本机时钟漂移影响精度,
        # 实际生产应该用 NTP 校准后的 TimeSync,但本测试只关心 dry_run 行为。
        ts = TimeSync(offset_s=0.0)
        sched = GrabScheduler(cfg, ts)
        sessions = self._make_sessions(3)

        async def go():
            return await sched.run(sessions, dry_run=True)

        summary = run(go())
        # 3 个虚拟结果
        self.assertEqual(len(summary.results), 3)
        for r in summary.results:
            self.assertFalse(r.success)
            self.assertEqual(r.error_type, "DryRun")
        # preheat 必须真的调过(否则就没"模拟"了)
        for s in sessions:
            s.client.preheat.assert_called_once()

    def test_normal_run_does_call_grab(self):
        """dry_run=False(默认):会调 _grab_one。"""
        from Core.Zhipu.scheduler import GrabScheduler
        from Core.Zhipu.timesync import TimeSync

        cfg = AppConfig(
            accounts=[Account(name='t', phone='13800000000')],
            target_plan='Max',
            billing_cycle='yearly',
            pay_channel='alipay',
            max_concurrent=4,
        )
        # target_time 留空 → 立即触发
        ts = TimeSync(offset_s=0.0)
        sched = GrabScheduler(cfg, ts)
        sessions = self._make_sessions(2)

        # mock _grab_one 让它返回成功
        async def fake_grab_one(sess, sem):
            async with sem:
                return AccountResult(
                    account_name=sess.account.name,
                    success=True,
                    latency_ms=10.0,
                )

        sched._grab_one = fake_grab_one

        async def go():
            return await sched.run(sessions)

        summary = run(go())
        self.assertEqual(summary.success_count, 2)
        for r in summary.results:
            self.assertTrue(r.success)

    def test_semaphore_limits_concurrency(self):
        """max_concurrent=2 + 5 个账号 → 同时最多 2 个 _grab_one 在运行。"""
        from Core.Zhipu.scheduler import GrabScheduler
        from Core.Zhipu.timesync import TimeSync

        cfg = AppConfig(
            accounts=[Account(name='t', phone='13800000000')],
            target_plan='Max',
            billing_cycle='yearly',
            pay_channel='alipay',
            max_concurrent=2,
        )
        ts = TimeSync(offset_s=0.0)
        sched = GrabScheduler(cfg, ts)
        sessions = self._make_sessions(5)

        # 用当前正在跑的协程数来验证 semaphore
        in_flight = [0]
        peak_in_flight = [0]

        async def fake_grab_one(sess, sem):
            async with sem:
                in_flight[0] += 1
                peak_in_flight[0] = max(peak_in_flight[0], in_flight[0])
                await asyncio.sleep(0.05)  # 让别的协程有机会进入 sem
                in_flight[0] -= 1
                return AccountResult(
                    account_name=sess.account.name, success=True, latency_ms=50.0,
                )

        sched._grab_one = fake_grab_one

        async def go():
            return await sched.run(sessions)

        summary = run(go())
        self.assertEqual(summary.success_count, 5)
        self.assertLessEqual(peak_in_flight[0], 2, "并发超限!")
        self.assertGreaterEqual(peak_in_flight[0], 1)


def _wrap_with_mock(coro_factory):
    """小工具:把协程函数包成 scheduler 方法(此处我们直接调 _grab_with_adaptive_retry)。"""
    return coro_factory


if __name__ == "__main__":
    unittest.main()