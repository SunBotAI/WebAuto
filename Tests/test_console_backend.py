"""console_backend 单测.

覆盖:
- AccountProgress.to_row 状态映射
- add_account / remove_account / update_account_phone
- resolve_target_ts(倒计时/绝对时间)
- state_to_appconfig_kwargs 转换(含 v5.x plan_groups 多组路径)
- make_progress_rows 表格格式化
- add_plan_group / remove_plan_group / toggle_plan_group / make_plan_group_rows
- SMS 登录流程(login_by_sms + 格式化)
"""
import asyncio
import time
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from Tools.console import _format_sms_result
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
    update_account_phone,
)


class AccountProgressRowTest(unittest.TestCase):
    def test_waiting_state(self):
        p = AccountProgress(name="acc1", state="waiting", phone="138xxxxxxxx")
        row = p.to_row()
        self.assertEqual(row[0], "acc1")
        self.assertIn("等", row[1])

    def test_success_state_shows_order_and_latency(self):
        from dataclasses import dataclass
        @dataclass
        class FakeOrder:
            order_id: str = "ORD-1"
            biz_id: str = "biz-abc"
            pay_url: str = "https://pay/..."
        p = AccountProgress(
            name="acc1", state="success",
            biz_id="biz-abc", order_no="ORD-1",
            pay_url="https://pay/...",
            latency_ms=234.5,
        )
        # 模拟 _run_console_job 把 order 写到 progress 上的行为
        # 这里直接断言 to_row 的逻辑
        row = p.to_row()
        self.assertEqual(row[0], "acc1")
        self.assertIn("成功", row[1])
        # order 字段展示 bizId 或 orderNo,二选一非空
        self.assertIn("ORD-1", row[2])
        self.assertIn("234", row[3])  # latency_ms

    def test_sold_out_state(self):
        p = AccountProgress(name="acc1", state="sold_out", last_error="全部档位售罄", attempts=5)
        row = p.to_row()
        self.assertIn("售罄", row[1])
        # last_error 优先于 attempts 展示
        self.assertIn("全部档位", row[3])

    def test_sold_out_state_no_error_falls_back_to_attempts(self):
        p = AccountProgress(name="acc1", state="sold_out", attempts=5)
        row = p.to_row()
        self.assertIn("售罄", row[1])
        self.assertIn("5 次", row[3])

    def test_risk_blocked_state(self):
        p = AccountProgress(name="acc1", state="risk_blocked", last_error="403")
        row = p.to_row()
        self.assertIn("风控", row[1])

    def test_dry_run_state(self):
        p = AccountProgress(name="acc1", state="dry_run")
        row = p.to_row()
        self.assertIn("dry", row[1])


class AddRemoveAccountTest(unittest.TestCase):
    def test_add_one_account(self):
        s = ConsoleState()
        s = add_account(s, name="账号1", phone="138xxxxxxxx")
        self.assertEqual(len(s.accounts), 1)
        self.assertEqual(s.accounts[0]["name"], "账号1")
        self.assertEqual(s.accounts[0]["phone"], "138xxxxxxxx")
        self.assertTrue(s.accounts[0]["enabled"])

    def test_add_default_name(self):
        s = ConsoleState()
        s = add_account(s)
        s = add_account(s)
        self.assertEqual(s.accounts[0]["name"], "账号1")
        self.assertEqual(s.accounts[1]["name"], "账号2")

    def test_add_duplicate_name_skipped(self):
        s = ConsoleState()
        s = add_account(s, name="dup", phone="1")
        s = add_account(s, name="dup", phone="2")
        self.assertEqual(len(s.accounts), 1)

    def test_remove_by_name(self):
        s = ConsoleState()
        s = add_account(s, name="a", phone="1")
        s = add_account(s, name="b", phone="2")
        s = remove_account(s, "a")
        self.assertEqual(len(s.accounts), 1)
        self.assertEqual(s.accounts[0]["name"], "b")

    def test_remove_nonexistent_is_safe(self):
        s = ConsoleState()
        s = add_account(s, name="a", phone="1")
        s = remove_account(s, "zzz")
        self.assertEqual(len(s.accounts), 1)

    def test_update_phone(self):
        s = ConsoleState()
        s = add_account(s, name="a", phone="old")
        s = update_account_phone(s, "a", "new")
        self.assertEqual(s.accounts[0]["phone"], "new")


class ResolveTargetTsTest(unittest.TestCase):
    def test_countdown_mode(self):
        s = ConsoleState(time_mode="countdown", countdown_sec=30)
        s.started_at = 1000.0
        # 倒计时 30s,started_at=1000,目标 1030
        self.assertAlmostEqual(resolve_target_ts(s), 1030.0)

    def test_absolute_mode(self):
        s = ConsoleState(time_mode="absolute", absolute_time="2099-01-01 12:00:00")
        ts = resolve_target_ts(s)
        # 2099-01-01 12:00:00 的 timestamp
        expected = datetime(2099, 1, 1, 12, 0, 0).timestamp()
        self.assertAlmostEqual(ts, expected, places=0)

    def test_absolute_invalid_falls_back_to_immediate(self):
        s = ConsoleState(time_mode="absolute", absolute_time="not a date")
        ts = resolve_target_ts(s)
        # 立即触发:time.time() + 0.5
        self.assertLess(abs(ts - time.time()), 5)

    def test_countdown_no_started_at_immediate(self):
        s = ConsoleState(time_mode="countdown")
        s.started_at = None
        ts = resolve_target_ts(s)
        self.assertLess(abs(ts - time.time()), 5)


class StateToAppConfigTest(unittest.TestCase):
    def test_basic_conversion(self):
        s = ConsoleState(
            target_plan="Max",
            target_plans=["Max", "Pro"],
            billing_cycle="yearly",
            pay_channel="alipay",
            max_concurrent=8,
            preheat_seconds=10,
        )
        s = add_account(s, name="a", phone="138xxxxxxxx")
        s = add_account(s, name="b", phone="139xxxxxxxx")
        kwargs = state_to_appconfig_kwargs(s)
        self.assertEqual(kwargs["target_plan"], "Max")
        self.assertEqual(kwargs["target_plans"], ["Max", "Pro"])
        self.assertEqual(kwargs["billing_cycle"], "yearly")
        self.assertEqual(kwargs["max_concurrent"], 8)
        self.assertEqual(len(kwargs["accounts"]), 2)

    def test_downgrade_disabled(self):
        s = ConsoleState(downgrade=False, target_plan="Max", target_plans=["Max", "Pro"])
        kwargs = state_to_appconfig_kwargs(s)
        # 不降级时只保留 target_plan 本身
        self.assertEqual(kwargs["target_plans"], ["Max"])

    def test_skips_accounts_without_phone_or_token(self):
        s = ConsoleState()
        s = add_account(s, name="no-phone")  # 没 phone
        s = add_account(s, name="with-phone", phone="138xxxxxxxx")
        kwargs = state_to_appconfig_kwargs(s)
        self.assertEqual(len(kwargs["accounts"]), 1)
        self.assertEqual(kwargs["accounts"][0]["name"], "with-phone")


class MakeProgressRowsTest(unittest.TestCase):
    def test_empty_progress_returns_placeholder(self):
        rows = make_progress_rows({})
        self.assertEqual(rows, [["(无账号)", "-", "-", "-"]])

    def test_progress_to_rows(self):
        s = ConsoleState()
        s.progress["a"] = AccountProgress(name="a", state="success", order_no="O1", latency_ms=100)
        s.progress["b"] = AccountProgress(name="b", state="sold_out", attempts=3)
        rows = make_progress_rows(s.progress)
        self.assertEqual(len(rows), 2)
        # 顺序按 dict 插入顺序
        self.assertEqual(rows[0][0], "a")
        self.assertEqual(rows[1][0], "b")


class MakeSummaryTest(unittest.TestCase):
    def test_running_with_started_at_shows_elapsed(self):
        s = ConsoleState(running=True, started_at=time.time() - 30)
        summary = make_summary(s)
        self.assertIn("抢单中", summary)

    def test_final_summary_used_after_done(self):
        s = ConsoleState(running=False, final_summary="2/4 成功")
        summary = make_summary(s)
        self.assertEqual(summary, "2/4 成功")


# ============================================================
# plan_groups 多套餐配置测试(v5.x)
# ============================================================

class PlanGroupsTest(unittest.TestCase):
    def test_add_one_group(self):
        s = ConsoleState()
        s = add_plan_group(s, name="Max年付", target_plan="Max", billing_cycle="yearly")
        self.assertEqual(len(s.plan_groups), 1)
        self.assertEqual(s.plan_groups[0]["name"], "Max年付")
        self.assertEqual(s.plan_groups[0]["target_plan"], "Max")
        self.assertEqual(s.plan_groups[0]["fallback_within_group"], [])

    def test_add_default_name_auto_numbered(self):
        s = ConsoleState()
        s = add_plan_group(s)
        s = add_plan_group(s)
        self.assertEqual(s.plan_groups[0]["name"], "组1")
        self.assertEqual(s.plan_groups[1]["name"], "组2")

    def test_add_duplicate_name_skipped(self):
        s = ConsoleState()
        s = add_plan_group(s, name="dup")
        s = add_plan_group(s, name="dup")
        self.assertEqual(len(s.plan_groups), 1)

    def test_remove_by_name(self):
        s = ConsoleState()
        s = add_plan_group(s, name="a")
        s = add_plan_group(s, name="b")
        s = remove_plan_group(s, "a")
        self.assertEqual(len(s.plan_groups), 1)
        self.assertEqual(s.plan_groups[0]["name"], "b")

    def test_remove_nonexistent_is_safe(self):
        s = ConsoleState()
        s = add_plan_group(s, name="a")
        s = remove_plan_group(s, "zzz")
        self.assertEqual(len(s.plan_groups), 1)

    def test_toggle_enabled(self):
        s = ConsoleState()
        s = add_plan_group(s, name="g")
        self.assertTrue(s.plan_groups[0]["enabled"])
        s = toggle_plan_group(s, "g")
        self.assertFalse(s.plan_groups[0]["enabled"])
        s = toggle_plan_group(s, "g")
        self.assertTrue(s.plan_groups[0]["enabled"])

    def test_make_plan_group_rows_empty(self):
        s = ConsoleState()
        rows = make_plan_group_rows(s)
        self.assertEqual(len(rows), 1)
        self.assertIn("默认", rows[0][0])

    def test_make_plan_group_rows_basic(self):
        s = ConsoleState()
        s = add_plan_group(
            s,
            name="Max年付",
            target_plan="Max",
            billing_cycle="yearly",
            pay_channel="alipay",
            use_pinhaomo=True,
            fallback_within_group=["Pro", "Lite"],
            notes="主力配置",
        )
        rows = make_plan_group_rows(s)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Max年付")
        self.assertEqual(rows[0][1], "Max")
        self.assertEqual(rows[0][2], "yearly")
        self.assertEqual(rows[0][3], "alipay")
        self.assertEqual(rows[0][4], "✅")  # use_pinhaomo
        self.assertEqual(rows[0][5], "Pro→Lite")
        self.assertEqual(rows[0][6], "✅")  # enabled
        self.assertEqual(rows[0][7], "主力配置")

    def test_make_plan_group_rows_disabled(self):
        s = ConsoleState()
        s = add_plan_group(s, name="g", use_pinhaomo=False)
        rows = make_plan_group_rows(s)
        self.assertEqual(rows[0][4], "❌")  # use_pinhaomo=False

    def test_state_to_appconfig_kwargs_legacy_single(self):
        """plan_groups 为空时,沿用旧的单套餐字段路径(向后兼容)。"""
        s = ConsoleState(
            target_plan="Max",
            target_plans=["Max", "Pro"],
            billing_cycle="yearly",
            pay_channel="alipay",
            downgrade=True,
        )
        s = add_account(s, name="a", phone="138xxxxxxxx")
        kwargs = state_to_appconfig_kwargs(s)
        # 旧字段还在
        self.assertEqual(kwargs["target_plan"], "Max")
        self.assertEqual(kwargs["target_plans"], ["Max", "Pro"])
        self.assertNotIn("plan_groups", kwargs)

    def test_state_to_appconfig_kwargs_multi_groups(self):
        """plan_groups 非空时,直接透传(走新多组路径)。"""
        s = ConsoleState()
        s = add_plan_group(s, name="A", target_plan="Max", billing_cycle="yearly")
        s = add_plan_group(s, name="B", target_plan="Lite", billing_cycle="monthly")
        s = add_account(s, name="a", phone="138xxxxxxxx")
        kwargs = state_to_appconfig_kwargs(s)
        self.assertNotIn("target_plan", kwargs)
        self.assertIn("plan_groups", kwargs)
        self.assertEqual(len(kwargs["plan_groups"]), 2)
        names = [g["name"] for g in kwargs["plan_groups"]]
        self.assertEqual(names, ["A", "B"])

    def test_state_to_appconfig_kwargs_disabled_group_excluded(self):
        s = ConsoleState()
        s = add_plan_group(s, name="A")  # 默认 enabled=True
        s = add_plan_group(s, name="B")
        s = toggle_plan_group(s, "B")    # 切到 enabled=False
        kwargs = state_to_appconfig_kwargs(s)
        # 启用过滤:enabled=False 的组不进 AppConfig
        self.assertEqual([g["name"] for g in kwargs["plan_groups"]], ["A"])

    def test_add_plan_group_does_not_mutate_input_state(self):
        """gradio State 不可变:函数应返回新 state,不修改原 state。"""
        s = ConsoleState()
        s = add_plan_group(s, name="a")
        original_groups = list(s.plan_groups)
        s2 = add_plan_group(s, name="b")
        # 原 state 没动
        self.assertEqual(len(s.plan_groups), len(original_groups))
        # 新 state 多了一个组
        self.assertEqual(len(s2.plan_groups), len(original_groups) + 1)

    def test_remove_plan_group_does_not_mutate_input_state(self):
        s = ConsoleState()
        s = add_plan_group(s, name="a")
        s = add_plan_group(s, name="b")
        s2 = remove_plan_group(s, "a")
        # 原 state 还是 2 组
        self.assertEqual(len(s.plan_groups), 2)
        # 新 state 1 组
        self.assertEqual(len(s2.plan_groups), 1)


# ============================================================
# SMS 登录流程测试(v2.4 控制台集成)
# ============================================================

class SmsLoginTest(unittest.TestCase):
    """测试控制台里的 SMS 登录区 — 复用 CredentialBackend.login_by_sms()。

    Mock ApiClient 避免真实网络请求。
    """

    def test_format_sms_result_code_sent(self):
        """阶段1:发送验证码 → 格式化为可读文本。"""
        result = {
            "stage": "code_sent",
            "success": True,
            "message": "验证码已发送到 138****0000,请在下方填入收到的 6 位短信码",
        }
        text = _format_sms_result(result)
        self.assertIn("code_sent", text)
        self.assertIn("138****0000", text)
        self.assertIn("✅ 成功", text)

    def test_format_sms_result_done_success(self):
        """阶段2:登录成功 → 包含 user_id / customer_number。"""
        result = {
            "stage": "done",
            "success": True,
            "message": "登录成功",
            "user_id": "u-12345",
            "customer_number": "C0001",
            "expires_hint": "",
        }
        text = _format_sms_result(result)
        self.assertIn("done", text)
        self.assertIn("u-12345", text)
        self.assertIn("C0001", text)
        self.assertIn("✅ 成功", text)

    def test_format_sms_result_done_failure(self):
        """阶段2:登录失败 → 显示 ❌ 失败。"""
        result = {
            "stage": "done",
            "success": False,
            "message": "短信校验通过但未拿到新凭证",
        }
        text = _format_sms_result(result)
        self.assertIn("done", text)
        self.assertIn("未拿到新凭证", text)
        self.assertIn("❌ 失败", text)

    def test_format_sms_result_error_stage(self):
        """前置校验失败:账号名/手机号为空。"""
        result = {"stage": "error", "success": False, "message": "账号名不能为空"}
        text = _format_sms_result(result)
        self.assertIn("error", text)
        self.assertIn("账号名不能为空", text)

    def test_login_by_sms_stage1_sends_code(self):
        """阶段1:空码 → login_by_sms 调 PATH_SMS_CODE,返回 code_sent。"""
        from Tools.credential_backend import CredentialBackend

        backend = CredentialBackend()

        # Mock ApiClient(避免真实 HTTP)
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value={"code": 200, "data": {}})

        with patch(
            "Tools.credential_backend.ApiClient",
            return_value=mock_client,
        ):
            result = asyncio.run(backend.login_by_sms("test_acc", "13800000000"))

        self.assertEqual(result["stage"], "code_sent")
        self.assertTrue(result["success"])
        # 真实调了一次 PATH_SMS_CODE
        self.assertEqual(mock_client.request.call_count, 1)
        called_path = mock_client.request.call_args[0][1]
        self.assertIn("13800000000", called_path)

    def test_login_by_sms_stage2_with_code(self):
        """阶段2:带码 → 调 PATH_CHECK_SMS_CODE,返回 done。"""
        from Tools.credential_backend import CredentialBackend

        backend = CredentialBackend()

        # 模拟 PATH_CHECK_SMS_CODE 响应 + 拿新 token
        mock_client = AsyncMock()
        mock_client._last_set_cookies = ["acw_tc=abc; Path=/", "atlas_t=xyz; Path=/"]
        mock_client.request = AsyncMock(return_value={
            "code": 200,
            "data": {"token": "test-token-123"},
        })

        with patch(
            "Tools.credential_backend.ApiClient",
            return_value=mock_client,
        ):
            with patch.object(
                backend,
                "_verify_token",
                new=AsyncMock(return_value={
                    "valid": True, "error": "",
                    "user_id": "u-test", "customer_number": "C-test",
                    "expires_hint": "",
                }),
            ):
                with patch.object(
                    backend,
                    "_get_store",
                    return_value=MagicMock(upsert_account=MagicMock()),
                ):
                    result = asyncio.run(
                        backend.login_by_sms("test_acc", "13800000000", sms_code="123456")
                    )

        self.assertEqual(result["stage"], "done")
        self.assertTrue(result["success"])
        # 真实调了一次 PATH_CHECK_SMS_CODE,code 应是 123456
        called_path = mock_client.request.call_args[0][1]
        self.assertIn("123456", called_path)

    def test_login_by_sms_stage2_invalid_token(self):
        """阶段2:_verify_token 返回 invalid → success=False。"""
        from Tools.credential_backend import CredentialBackend

        backend = CredentialBackend()

        mock_client = AsyncMock()
        mock_client._last_set_cookies = ["acw_tc=abc; Path=/"]
        mock_client.request = AsyncMock(return_value={
            "code": 200,
            "data": {"token": "bad-token"},
        })

        with patch(
            "Tools.credential_backend.ApiClient",
            return_value=mock_client,
        ):
            with patch.object(
                backend,
                "_verify_token",
                new=AsyncMock(return_value={"valid": False, "error": "401 unauthorized"}),
            ):
                result = asyncio.run(
                    backend.login_by_sms("test_acc", "13800000000", sms_code="123456")
                )

        self.assertEqual(result["stage"], "done")
        self.assertFalse(result["success"])
        self.assertIn("401", result["message"])

    def test_login_by_sms_validation_empty_name(self):
        """前置校验:账号名为空 → 直接 error,不发请求。"""
        from Tools.credential_backend import CredentialBackend

        backend = CredentialBackend()
        result = asyncio.run(backend.login_by_sms("", "13800000000"))
        self.assertEqual(result["stage"], "error")
        self.assertIn("账号名不能为空", result["message"])

    def test_login_by_sms_validation_empty_phone(self):
        """前置校验:手机号为空 → 直接 error。"""
        from Tools.credential_backend import CredentialBackend

        backend = CredentialBackend()
        result = asyncio.run(backend.login_by_sms("test_acc", ""))
        self.assertEqual(result["stage"], "error")
        self.assertIn("手机号不能为空", result["message"])


if __name__ == "__main__":
    unittest.main()