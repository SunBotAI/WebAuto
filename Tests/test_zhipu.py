"""Zhipu 子包单测.

覆盖:
- exceptions 继承链(继承自 WebAutoError)
- constants 端点和 productId 映射
- ApiClient 实例化 + headers 正确性
- BigModelApi 业务逻辑(mock httpx 真实响应)
- with_retry 重试策略
"""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from Core.Zhipu import (
    ApiClient, BigModelApi, with_retry,
    ZhipuError, NetworkError, RateLimitedError, AuthError,
    SoldOutError, ApiError, RetryableError,
    BASE_URL, PATH_BATCH_PREVIEW, PATH_CREATE_BANK_ORDER,
    PRODUCT_ID_REFERENCE, PLAN_TIER_CODE, BILLING_CYCLE_CODE,
)
from Core.Zhipu.config import AppConfig, Account, Plan, BillingCycle, PayChannel
from Core.Errors import WebAutoError


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ExceptionsTest(unittest.TestCase):
    def test_all_zhipu_exceptions_inherit_webautoerror(self):
        """所有 Zhipu 异常必须继承 WebAutoError,统一 catch。"""
        for exc in (NetworkError, RateLimitedError, AuthError, SoldOutError,
                    ApiError, RetryableError):
            with self.subTest(exc=exc.__name__):
                self.assertTrue(issubclass(exc, WebAutoError))
                self.assertTrue(issubclass(exc, ZhipuError))

    def test_rate_limited_carries_retry_after(self):
        e = RateLimitedError(retry_after_ms=3000)
        self.assertEqual(e.retry_after_ms, 3000)
        self.assertIsInstance(e, WebAutoError)

    def test_api_error_carries_code_and_payload(self):
        e = ApiError("test", code=4002, payload={"detail": "sold out"})
        self.assertEqual(e.code, 4002)
        self.assertEqual(e.payload, {"detail": "sold out"})


class ConstantsTest(unittest.TestCase):
    def test_endpoints_are_under_bigmodel(self):
        for path in (PATH_BATCH_PREVIEW, PATH_CREATE_BANK_ORDER):
            with self.subTest(path=path):
                self.assertTrue(path.startswith("/api/"))
                self.assertIn("biz", path)

    def test_base_url(self):
        self.assertEqual(BASE_URL, "https://bigmodel.cn")

    def test_product_id_coverage(self):
        """3 tier x 3 period = 9 个 productId 都有。"""
        for tier in ("LITE", "PRO", "MAX"):
            for period in ("MONTHLY", "QUARTERLY", "YEARLY"):
                key = (tier, period)
                with self.subTest(key=key):
                    self.assertIn(key, PRODUCT_ID_REFERENCE)
                    self.assertTrue(PRODUCT_ID_REFERENCE[key].startswith("product-"))

    def test_tier_and_period_codes_match_enums(self):
        """常量映射和 Enum 成员必须对齐。"""
        self.assertEqual(PLAN_TIER_CODE["Max"], "MAX")
        self.assertEqual(PLAN_TIER_CODE["Pro"], "PRO")
        self.assertEqual(PLAN_TIER_CODE["Lite"], "LITE")
        self.assertEqual(BILLING_CYCLE_CODE["yearly"], "YEARLY")
        self.assertEqual(BILLING_CYCLE_CODE["monthly"], "MONTHLY")


class ApiClientTest(unittest.TestCase):
    def _make_cfg(self, **overrides):
        defaults = dict(
            accounts=[Account(name='test', phone='13800000000')],
            target_plan='Max',
            billing_cycle='yearly',
            pay_channel='alipay',
        )
        defaults.update(overrides)
        return AppConfig(**defaults)

    def test_init_with_token_sets_auth_header(self):
        cfg = self._make_cfg()
        client = ApiClient(cfg, token='test-token', account_name='test')
        try:
            self.assertEqual(client._client.headers["Authorization"], "Bearer test-token")
        finally:
            run(client.aclose())

    def test_init_with_cookie_sets_cookie_header(self):
        cfg = self._make_cfg()
        client = ApiClient(cfg, cookie='sid=abc; tok=def', account_name='test')
        try:
            self.assertIn("sid=abc", client._client.headers["Cookie"])
        finally:
            run(client.aclose())

    def test_update_credentials(self):
        cfg = self._make_cfg()
        client = ApiClient(cfg, token='old', account_name='test')
        try:
            client.update_credentials(token='new')
            self.assertEqual(client._client.headers["Authorization"], "Bearer new")
            client.update_credentials(cookie='sid=new')
            self.assertIn("sid=new", client._client.headers["Cookie"])
        finally:
            run(client.aclose())

    def test_preheat_swallows_errors(self):
        cfg = self._make_cfg()
        client = ApiClient(cfg, token='t', account_name='test')
        try:
            # 即使请求失败也不抛
            run(client.preheat())
        finally:
            run(client.aclose())

    def test_request_translates_429_to_rate_limited(self):
        import httpx as _httpx
        cfg = self._make_cfg()
        client = ApiClient(cfg, token='t', account_name='test')
        try:
            fake_resp = MagicMock(spec=_httpx.Response)
            fake_resp.status_code = 429
            fake_resp.headers = _httpx.Headers({"Retry-After": "5", "set-cookie": ""})
            fake_resp.is_success = False
            client._client.request = AsyncMock(return_value=fake_resp)
            with self.assertRaises(RateLimitedError) as ctx:
                run(client.request("GET", "/api/test"))
            self.assertEqual(ctx.exception.retry_after_ms, 5000)
        finally:
            run(client.aclose())

    def test_request_translates_5xx_to_retryable(self):
        import httpx as _httpx
        cfg = self._make_cfg()
        client = ApiClient(cfg, token='t', account_name='test')
        try:
            fake_resp = MagicMock(spec=_httpx.Response)
            fake_resp.status_code = 503
            fake_resp.headers = _httpx.Headers({"set-cookie": ""})
            fake_resp.is_success = False
            client._client.request = AsyncMock(return_value=fake_resp)
            with self.assertRaises(RetryableError):
                run(client.request("GET", "/api/test"))
        finally:
            run(client.aclose())

    def test_request_translates_auth_error(self):
        import httpx as _httpx
        cfg = self._make_cfg()
        client = ApiClient(cfg, token='t', account_name='test')
        try:
            fake_resp = MagicMock(spec=_httpx.Response)
            fake_resp.status_code = 200
            fake_resp.headers = _httpx.Headers({"set-cookie": ""})
            fake_resp.json.return_value = {"code": 401, "msg": "未登录"}
            fake_resp.is_success = True
            client._client.request = AsyncMock(return_value=fake_resp)
            with self.assertRaises(AuthError):
                run(client.request("GET", "/api/test"))
        finally:
            run(client.aclose())


class WithRetryTest(unittest.TestCase):
    """测试 with_retry 的指数退避 + 异常分类处理。"""

    def test_returns_first_success(self):
        calls = [0]

        async def op():
            calls[0] += 1
            return "ok"

        result = run(with_retry(op, times=3, delay_ms=1, backoff_factor=2,
                                on_429_wait_ms=1, op_desc="t"))
        self.assertEqual(result, "ok")
        self.assertEqual(calls[0], 1)

    def test_retries_network_error(self):
        calls = [0]

        async def op():
            calls[0] += 1
            if calls[0] < 3:
                raise NetworkError("mocked network")
            return "ok"

        result = run(with_retry(op, times=5, delay_ms=1, backoff_factor=1.0,
                                on_429_wait_ms=1, op_desc="t"))
        self.assertEqual(result, "ok")
        self.assertEqual(calls[0], 3)

    def test_does_not_retry_soldout(self):
        calls = [0]

        async def op():
            calls[0] += 1
            raise SoldOutError("mocked sold out")

        with self.assertRaises(SoldOutError):
            run(with_retry(op, times=5, delay_ms=1, backoff_factor=2.0,
                           on_429_wait_ms=1, op_desc="t"))
        # 售罄不应该重试
        self.assertEqual(calls[0], 1)

    def test_does_not_retry_auth_error(self):
        calls = [0]

        async def op():
            calls[0] += 1
            raise AuthError("mocked auth")

        with self.assertRaises(AuthError):
            run(with_retry(op, times=5, delay_ms=1, backoff_factor=2.0,
                           on_429_wait_ms=1, op_desc="t"))
        self.assertEqual(calls[0], 1)


class BigModelApiTest(unittest.TestCase):
    """业务层单测:用 mock 跑通完整下单链路。"""

    def _setup(self):
        cfg = AppConfig(
            accounts=[Account(name='test', phone='13800000000')],
            target_plan='Max',
            billing_cycle='yearly',
            pay_channel='alipay',
        )
        client = ApiClient(cfg, token='fake-token', account_name='test')
        return BigModelApi(client, cfg), client

    def test_get_customer_info(self):
        api, client = self._setup()
        try:
            import httpx as _httpx
            fake_resp = MagicMock(spec=_httpx.Response)
            fake_resp.status_code = 200
            fake_resp.headers = _httpx.Headers({"set-cookie": ""})
            fake_resp.json.return_value = {
                "code": 200,
                "data": {
                    "id": "user-123",
                    "customerNumber": "C001",
                    "nickName": "tester",
                    "acState": "AC_SUCCESS",
                }
            }
            fake_resp.is_success = True
            client._client.request = AsyncMock(return_value=fake_resp)

            info = run(api.get_customer_info())
            self.assertEqual(info.user_id, "user-123")
            self.assertEqual(info.customer_number, "C001")
            self.assertTrue(info.authenticated)
        finally:
            run(client.aclose())

    def test_batch_preview_parses_sold_out(self):
        api, client = self._setup()
        try:
            import httpx as _httpx
            fake_resp = MagicMock(spec=_httpx.Response)
            fake_resp.status_code = 200
            fake_resp.headers = _httpx.Headers({"set-cookie": ""})
            # 模拟一个售罄 + 一个可买的混合响应
            fake_resp.json.return_value = {
                "code": 200,
                "data": {
                    "productList": [
                        {
                            "productId": "product-max-y",
                            "tier": "MAX",
                            "subscribePeriod": "YEARLY",
                            "soldOut": True,
                            "canPurchase": False,
                            "payAmount": 469.0,
                            "originalAmount": 469.0,
                        },
                        {
                            "productId": "product-pro-y",
                            "tier": "PRO",
                            "subscribePeriod": "YEARLY",
                            "soldOut": False,
                            "canPurchase": True,
                            "payAmount": 149.0,
                            "originalAmount": 149.0,
                        },
                    ]
                }
            }
            fake_resp.is_success = True
            client._client.request = AsyncMock(return_value=fake_resp)

            preview = run(api.batch_preview())
            self.assertEqual(len(preview.plans), 2)
            max_y = preview.find("MAX", "YEARLY")
            self.assertTrue(max_y.sold_out)
            pro_y = preview.find("PRO", "YEARLY")
            self.assertFalse(pro_y.sold_out)
        finally:
            run(client.aclose())

    def test_pick_best_available_downgrades(self):
        """MAX 售罄 → 自动降级到 PRO(target_plans=[Max, Pro])。"""
        cfg = AppConfig(
            accounts=[Account(name='test', phone='13800000000')],
            target_plan='Max',
            target_plans=[Plan.MAX, Plan.PRO],   # 降级优先级
            billing_cycle='yearly',
            pay_channel='alipay',
        )
        client = ApiClient(cfg, token='fake-token', account_name='test')
        api = BigModelApi(client, cfg)
        try:
            preview = _preview_with_only_pro_available()
            picked = api.pick_best_available(preview)
            self.assertEqual(picked.tier, "PRO")
        finally:
            run(client.aclose())

    def test_pick_best_available_all_sold_out_raises(self):
        api, client = self._setup()
        try:
            preview = _preview_all_sold_out()
            with self.assertRaises(SoldOutError):
                api.pick_best_available(preview)
        finally:
            run(client.aclose())


def _preview_with_only_pro_available():
    from Core.Zhipu.api import PreviewResult, PlanPreview
    return PreviewResult(plans=[
        PlanPreview(product_id="product-max-y", tier="MAX", period="YEARLY",
                    sold_out=True, can_purchase=False, pay_amount=469.0, original_amount=469.0),
        PlanPreview(product_id="product-pro-y", tier="PRO", period="YEARLY",
                    sold_out=False, can_purchase=True, pay_amount=149.0, original_amount=149.0),
    ])


class PreviewCheckTest(unittest.TestCase):
    """qtaxm/glm-rush 模式:preview_single + check_biz_id + EXPIRE 自动重试。"""

    def _setup(self):
        cfg = AppConfig(
            accounts=[Account(name='test', phone='13800000000')],
            target_plan='Max',
            target_plans=[Plan.MAX, Plan.PRO],
            billing_cycle='yearly',
            pay_channel='alipay',
        )
        client = ApiClient(cfg, token='fake', account_name='test')
        return BigModelApi(client, cfg), client

    def _mock_response(self, json_body, status=200):
        """构造一个 httpx.Response mock,带 httpx.Headers(set-cookie 可空)。"""
        import httpx as _httpx
        fake_resp = MagicMock(spec=_httpx.Response)
        fake_resp.status_code = status
        fake_resp.headers = _httpx.Headers({"set-cookie": ""})
        fake_resp.json.return_value = json_body
        fake_resp.is_success = 200 <= status < 300
        fake_resp.text = json.dumps(json_body)
        return fake_resp

    def test_preview_single_returns_biz_id(self):
        """preview 拿到 bizId → 返回 data dict."""
        api, client = self._setup()
        try:
            client._client.request = AsyncMock(return_value=self._mock_response({
                "code": 200,
                "data": {"bizId": "biz-abc-123", "payAmount": 469.0, "originalAmount": 469.0},
            }))
            data = run(api.preview_single("MAX", "YEARLY"))
            self.assertIsNotNone(data)
            self.assertEqual(data["bizId"], "biz-abc-123")
            self.assertEqual(data["payAmount"], 469.0)
        finally:
            run(client.aclose())

    def test_preview_single_sold_out_returns_none(self):
        """preview 售罄(bizId=null)→ 返回 None,让上层降级。"""
        api, client = self._setup()
        try:
            client._client.request = AsyncMock(return_value=self._mock_response({
                "code": 200,
                "data": {"bizId": None},
            }))
            data = run(api.preview_single("MAX", "YEARLY"))
            self.assertIsNone(data)
        finally:
            run(client.aclose())

    def test_preview_single_missing_product_id_raises(self):
        """没找到 productId 应该抛 ApiError(让上层换档位)。"""
        api, client = self._setup()
        try:
            with self.assertRaises(ApiError):
                run(api.preview_single("NONEXIST", "YEARLY"))
        finally:
            run(client.aclose())

    def test_check_biz_id_valid(self):
        """check 返回 data="VALID" 或 dict(valid=True) → 有效。"""
        api, client = self._setup()
        try:
            # 字符串 "VALID" 形式
            client._client.request = AsyncMock(return_value=self._mock_response({
                "code": 200, "data": "VALID",
            }))
            self.assertTrue(run(api.check_biz_id("biz-abc")))
            # dict(valid=True) 形式
            client._client.request = AsyncMock(return_value=self._mock_response({
                "code": 200, "data": {"valid": True, "expireIn": 600},
            }))
            self.assertTrue(run(api.check_biz_id("biz-def")))
        finally:
            run(client.aclose())

    def test_check_biz_id_expire_raises(self):
        """check 返回 data="EXPIRE" → 抛 CheckExpireError。"""
        from Core.Zhipu import CheckExpireError
        api, client = self._setup()
        try:
            client._client.request = AsyncMock(return_value=self._mock_response({
                "code": 200, "data": "EXPIRE",
            }))
            with self.assertRaises(CheckExpireError):
                run(api.check_biz_id("biz-abc"))
        finally:
            run(client.aclose())

    def test_run_preview_check_chain_succeeds_on_first(self):
        """首次 preview + check 通过 → 直接下单。"""
        api, client = self._setup()
        try:
            # getCustomerInfo → preview → check → createBankOrder
            responses = [
                self._mock_response({"code": 200, "data": {
                    "id": "user-1", "customerNumber": "C1", "nickName": "u", "acState": "AC_SUCCESS"
                }}),  # getCustomerInfo
                self._mock_response({"code": 200, "data": {
                    "bizId": "biz-123", "payAmount": 469.0, "originalAmount": 469.0
                }}),  # preview
                self._mock_response({"code": 200, "data": "VALID"}),  # check
                self._mock_response({"code": 200, "data": {
                    "orderNo": "ORD-1", "bizId": "biz-123", "payUrl": "https://pay/1"
                }}),  # createBankOrder
            ]
            client._client.request = AsyncMock(side_effect=responses)
            order = run(api.run_preview_check_chain())
            self.assertEqual(order.order_id, "ORD-1")
            self.assertEqual(order.biz_id, "biz-123")
            self.assertEqual(order.raw["_selected_tier"], "MAX")
        finally:
            run(client.aclose())

    def test_run_preview_check_chain_retries_on_expire(self):
        """check EXPIRE → 立即重试 preview,直到成功(qtaxm 核心逻辑)。"""
        from Core.Zhipu import CheckExpireError
        api, client = self._setup()
        try:
            responses = [
                self._mock_response({"code": 200, "data": {
                    "id": "user-1", "customerNumber": "C1", "nickName": "u", "acState": "AC_SUCCESS"
                }}),  # getCustomerInfo
                # 第 1 次:preview 成功 → check EXPIRE
                self._mock_response({"code": 200, "data": {"bizId": "biz-bad", "payAmount": 469.0}}),
                self._mock_response({"code": 200, "data": "EXPIRE"}),  # check expire
                # 第 2 次:preview 成功 → check 通过 → 下单成功
                self._mock_response({"code": 200, "data": {"bizId": "biz-good", "payAmount": 469.0}}),
                self._mock_response({"code": 200, "data": "VALID"}),
                self._mock_response({"code": 200, "data": {
                    "orderNo": "ORD-2", "bizId": "biz-good", "payUrl": "https://pay/2"
                }}),
            ]
            client._client.request = AsyncMock(side_effect=responses)
            order = run(api.run_preview_check_chain())
            self.assertEqual(order.order_id, "ORD-2")
            self.assertEqual(order.biz_id, "biz-good")
            # 调用次数:1 (login) + 2 (preview) + 2 (check) + 1 (create) = 6
            self.assertEqual(client._client.request.await_count, 6)
        finally:
            run(client.aclose())

    def test_run_preview_check_chain_downgrades_tier(self):
        """MAX 售罄 → 降级到 PRO(qtaxm 模式的多档降级)。"""
        api, client = self._setup()
        try:
            responses = [
                self._mock_response({"code": 200, "data": {
                    "id": "user-1", "customerNumber": "C1", "nickName": "u", "acState": "AC_SUCCESS"
                }}),  # getCustomerInfo
                # MAX 售罄
                self._mock_response({"code": 200, "data": {"bizId": None}}),
                # PRO 成功
                self._mock_response({"code": 200, "data": {"bizId": "biz-pro", "payAmount": 149.0}}),
                self._mock_response({"code": 200, "data": "VALID"}),
                self._mock_response({"code": 200, "data": {
                    "orderNo": "ORD-PRO", "bizId": "biz-pro", "payUrl": "https://pay/pro"
                }}),
            ]
            client._client.request = AsyncMock(side_effect=responses)
            order = run(api.run_preview_check_chain())
            self.assertEqual(order.raw["_selected_tier"], "PRO")
            self.assertEqual(order.order_id, "ORD-PRO")
        finally:
            run(client.aclose())

    def test_run_preview_check_chain_all_sold_out_raises(self):
        api, client = self._setup()
        try:
            responses = [
                self._mock_response({"code": 200, "data": {
                    "id": "user-1", "customerNumber": "C1", "nickName": "u", "acState": "AC_SUCCESS"
                }}),
                # MAX 售罄
                self._mock_response({"code": 200, "data": {"bizId": None}}),
                # PRO 也售罄
                self._mock_response({"code": 200, "data": {"bizId": None}}),
            ]
            client._client.request = AsyncMock(side_effect=responses)
            with self.assertRaises(SoldOutError):
                run(api.run_preview_check_chain())
        finally:
            run(client.aclose())


def _preview_all_sold_out():
    from Core.Zhipu.api import PreviewResult, PlanPreview
    return PreviewResult(plans=[
        PlanPreview(product_id="product-max-y", tier="MAX", period="YEARLY",
                    sold_out=True, can_purchase=False, pay_amount=469.0, original_amount=469.0),
        PlanPreview(product_id="product-pro-y", tier="PRO", period="YEARLY",
                    sold_out=True, can_purchase=False, pay_amount=149.0, original_amount=149.0),
    ])


if __name__ == "__main__":
    unittest.main()