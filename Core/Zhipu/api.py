"""高阶 API 封装：实现完整下单请求链（已按真实抓包校准）。

接口基址：https://bigmodel.cn/api/  （需求文档里的 /biz/... 缺了 /api 前缀）

真实请求链（基于 2026-06-17 Playwright 抓包确认）：

    1. GET  /api/biz/customer/getCustomerInfo
       → 验证登录态，拿到 customerNumber / id / 实名信息
    2. POST /api/biz/pay/batch-preview
       → 一次性返回所有个人版套餐的 productId / 价格 / soldOut 状态
    3. （售罄时检测 soldOut；补货后 soldOut 变 false）
    4. 创建订单 → 跳转支付页 /subscribe-pay

注意：下单接口（createBankOrder）的真实参数需在补货后从点击"立即购买"
抓包确认（售罄状态下点购买会被前端拦截，抓不到完整请求体）。当前实现
按 batch-preview 拿到的 productId 构造下单请求，字段名做了多别名兜底。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from Core.Zhipu.config import AppConfig
from Core.Zhipu.constants import (
    BILLING_CYCLE_CODE,
    FIELD_CAN_PURCHASE,
    FIELD_FORBIDDEN,
    FIELD_SOLD_OUT,
    PATH_BATCH_PREVIEW,
    PATH_CHECK,
    PATH_CREATE_BANK_ORDER,
    PATH_CUSTOMER_INFO,
    PATH_ORDERS_PENDING,
    PATH_PREVIEW,
    PATH_PRICING,
    PAY_CHANNEL_CODE,
    PERIOD_BY_CAMPAIGN_KEYWORD,
    PLAN_TIER_CODE,
    PRODUCT_ID_REFERENCE,
    SUBSCRIBE_MODE_CONTINUOUS,
    TIER_BY_MONTHLY_PRICE,
)
from Core.Zhipu.exceptions import (
    ApiError,
    AuthError,
    CheckExpireError,
    SoldOutError,
)
from Core.Zhipu.http_client import ApiClient, with_retry
from Core.Zhipu.logger import get_logger

log = get_logger()


# ---------------------------------------------------------------------------
# 数据载体
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CustomerInfo:
    user_id: str              # 真实字段：id
    customer_number: str      # 真实字段：customerNumber
    nickname: str
    authenticated: bool       # acState == "AC_SUCCESS"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlanPreview:
    """batch-preview 里单个套餐的预览信息。"""

    product_id: str
    tier: str                 # LITE / PRO / MAX
    period: str               # MONTHLY / QUARTERLY / YEARLY
    sold_out: bool
    can_purchase: Optional[bool]
    pay_amount: float         # 实付金额（元）
    original_amount: float    # 原价（元）
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PreviewResult:
    """batch-preview 整体结果。"""

    plans: list[PlanPreview] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def find(self, tier: str, period: str) -> Optional[PlanPreview]:
        """按 tier + period 找匹配的套餐。"""
        for p in self.plans:
            if p.tier == tier and p.period == period:
                return p
        return None


@dataclass(slots=True)
class OrderResult:
    order_id: str
    biz_id: str = ""         # qtaxm/glm-rush: preview 拿到的 bizId,用于 check 校验
    pay_url: str = ""
    status: str = "WAIT_PAY"
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 服务
# ---------------------------------------------------------------------------


class BigModelApi:
    """面向一个账号会话的高阶 API。"""

    def __init__(self, client: ApiClient, config: AppConfig) -> None:
        self.client = client
        self.config = config
        self.account_name = client.account_name

    # ----------------------------------------------------------- 工具

    def _retry_kwargs(self, op_desc: str) -> dict[str, Any]:
        r = self.config.retry
        return dict(
            times=r.times,
            delay_ms=r.delay_ms,
            backoff_factor=r.backoff_factor,
            on_429_wait_ms=r.on_429_wait_ms,
            account_name=self.account_name,
            op_desc=op_desc,
        )

    # ----------------------------------------------------------- 步骤 1

    async def get_customer_info(self) -> CustomerInfo:
        """获取客户信息，同时验证登录态。"""
        data = await with_retry(
            lambda: self.client.request("GET", PATH_CUSTOMER_INFO),
            **self._retry_kwargs("getCustomerInfo"),
        )
        d = _extract_data(data)
        user_id = str(d.get("id") or "")
        customer_number = str(d.get("customerNumber") or "")
        nickname = str(d.get("nickName") or d.get("customerName") or "")
        ac_state = str(d.get("acState") or "")
        authenticated = ac_state == "AC_SUCCESS"
        info = CustomerInfo(
            user_id=user_id,
            customer_number=customer_number,
            nickname=nickname,
            authenticated=authenticated,
            raw=d,
        )
        log.debug(
            f"[{self.account_name}] customerInfo: id={user_id} "
            f"customerNumber={customer_number} acState={ac_state}"
        )
        return info

    # ----------------------------------------------------------- 步骤 2

    async def batch_preview(self) -> PreviewResult:
        """批量预览：一次性拿到所有个人版套餐的 productId/价格/售罄状态。

        这是抢购的关键接口——补货后 soldOut 会从 true 变 false。
        """
        payload = self._build_preview_payload()
        data = await with_retry(
            lambda: self.client.request("POST", PATH_BATCH_PREVIEW, json=payload),
            **self._retry_kwargs("batch-preview"),
        )
        d = _extract_data(data)
        # data 里有 productList 数组（真实抓包确认）
        items = d.get("productList") if isinstance(d, dict) else None
        if not isinstance(items, list):
            # 兜底：data 本身可能是数组
            items = d if isinstance(d, list) else []
        plans: list[PlanPreview] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            plans.append(_parse_plan(item))
        result = PreviewResult(plans=plans, raw=d)
        sold = sum(1 for p in plans if p.sold_out)
        log.info(
            f"[{self.account_name}] batch-preview: 共 {len(plans)} 个套餐，"
            f"{sold} 个售罄"
        )
        return result

    def _build_preview_payload(self) -> dict[str, Any]:
        """构造 batch-preview 请求体。

        真实抓包的请求体结构（售罄时前端仍会带这个 body 发请求）：
        实测 POST 无 body 也能返回完整 productList，因此这里给一个合理的
        入参，便于平台识别意图；具体字段在补货后可微调。
        """
        return {
            "subscribeMode": SUBSCRIBE_MODE_CONTINUOUS,
            "usePinhaomo": self.config.use_pinhaomo,
        }

    # ----------------------------------------------------------- 步骤 3 售罄检测

    def _locate_plan(
        self, preview: PreviewResult, tier: str, period: str
    ) -> Optional[PlanPreview]:
        """从 batch-preview 结果里定位指定 tier/period 的套餐。"""
        plan = preview.find(tier, period)
        if plan is None:
            # 兜底：用参考 productId 反查
            ref_id = PRODUCT_ID_REFERENCE.get((tier, period))
            if ref_id:
                for p in preview.plans:
                    if p.product_id == ref_id:
                        return p
        return plan

    def pick_best_available(self, preview: PreviewResult) -> PlanPreview:
        """按 config.target_plans 优先级，挑第一个可购买的套餐。

        例：target_plans=[Max, Pro] → 先试 Max 包年，售罄则试 Pro 包年，
        全部售罄才抛 :class:`SoldOutError`。这实现了"Max 抢不到就抢 Pro"。

        Returns:
            第一个可购买的 :class:`PlanPreview`。
        Raises:
            SoldOutError: 所有候选套餐都售罄/不可买。
            ApiError: batch-preview 没返回任何候选套餐。
        """
        period = BILLING_CYCLE_CODE[self.config.billing_cycle.value]
        missing: list[str] = []
        all_sold_out: list[str] = []

        for plan_enum in self.config.target_plans:
            tier = PLAN_TIER_CODE[plan_enum.value]
            plan = self._locate_plan(preview, tier, period)
            if plan is None:
                missing.append(f"{tier}/{period}")
                continue
            if plan.sold_out:
                all_sold_out.append(f"{tier}/{period}（{plan.product_id}）")
                log.info(
                    f"[{self.account_name}] 候选 {tier}/{period}"
                    f"（{plan.product_id}）售罄，尝试下一档"
                )
                continue
            if plan.can_purchase is False or plan.raw.get(FIELD_FORBIDDEN):
                all_sold_out.append(
                    f"{tier}/{period}（不可购买 canPurchase={plan.can_purchase}）"
                )
                continue
            # 命中可买的
            log.success(
                f"[{self.account_name}] 选中套餐 {tier}/{period}"
                f"（{plan.product_id}）可购买！实付 {plan.pay_amount} 元"
            )
            return plan

        # 走到这里说明全售罄
        if missing and not all_sold_out:
            # 一个候选都没匹配上（batch-preview 结构异常）
            log.warning(
                f"[{self.account_name}] batch-preview 未匹配到任何候选套餐: "
                f"{missing}。列出所有套餐："
            )
            for p in preview.plans:
                log.warning(
                    f"  - {p.product_id} tier={p.tier} period={p.period} "
                    f"soldOut={p.sold_out} pay={p.pay_amount}"
                )
            raise ApiError(
                f"batch-preview 未返回候选套餐 {missing}，"
                "可能需要更新 PRODUCT_ID_REFERENCE 或检查 batch-preview 入参"
            )
        raise SoldOutError(
            f"所有候选套餐均售罄/不可买: {all_sold_out}"
        )

    # 兼容旧调用名（保留以防外部引用）
    def check_target_sold_out(self, preview: PreviewResult) -> PlanPreview:
        """[已废弃] 旧名单套餐选择，内部转调 pick_best_available。"""
        return self.pick_best_available(preview)

    # ----------------------------------------------------------- 步骤 4 下单

    async def preview_single(
        self, tier: str, period: str, *, product_id: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """单次预览:直接返回 preview 接口的 data(包含 bizId)。

        这是 qtaxm/glm-rush 的关键路径——比 batch-preview 更快,因为不用拿所有套餐列表。

        Returns:
            成功时返回 data dict(bizId 等字段);
            售罄(bizId === null)时返回 None;
            接口报错时抛异常。
        """
        pid = product_id or PRODUCT_ID_REFERENCE.get((tier, period))
        if not pid:
            raise ApiError(f"未找到 tier={tier}/period={period} 对应的 productId")

        payload = {
            "productId": pid,
            "subscribeMode": SUBSCRIBE_MODE_CONTINUOUS,
            "subscribePeriod": period or BILLING_CYCLE_CODE[self.config.billing_cycle.value],
            "tier": tier,
            "usePinhaomo": self.config.use_pinhaomo,
        }
        data = await with_retry(
            lambda: self.client.request("POST", PATH_PREVIEW, json=payload),
            **self._retry_kwargs("preview"),
        )
        d = _extract_data(data)
        # preview 返回 {code: 200, data: {bizId: "xxx" | null, ...}}
        inner = d.get("bizId") if isinstance(d, dict) else None
        if inner is None:
            log.info(
                f"[{self.account_name}] preview tier={tier}/period={period} 售罄"
            )
            return None
        log.success(
            f"[{self.account_name}] preview 拿到 bizId={inner[:8]}... "
            f"(tier={tier}/period={period})"
        )
        return d

    async def check_biz_id(self, biz_id: str) -> bool:
        """bizId 有效性校验。

        Returns:
            True 表示 bizId 有效,可以继续下单;
            False 表示 bizId 已 EXPIRE,需要重新 preview。

        Raises:
            CheckExpireError: 当 data 字段是字符串 "EXPIRE" 时(qtaxm/glm-rush 的明确信号)。
        """
        data = await with_retry(
            lambda: self.client.request(
                "GET", PATH_CHECK, params={"bizId": biz_id}
            ),
            **self._retry_kwargs("check"),
        )
        # 直接读 data 字段,不走 _extract_data(它会把字符串包成 dict)
        raw = data.get("data") if isinstance(data, dict) else data
        # qtaxm 真实响应: {code: 200, data: "EXPIRE"} 或 {data: "VALID"}
        if isinstance(raw, str):
            if raw == "EXPIRE":
                log.warning(
                    f"[{self.account_name}] bizId={biz_id[:8]}... 已 EXPIRE"
                )
                raise CheckExpireError(f"bizId {biz_id[:8]}... EXPIRE")
            return True
        # _extract_data 会把字符串包成 {"_data": "EXPIRE"} 形式,这里兜底
        if isinstance(raw, dict) and raw.get("_data") == "EXPIRE":
            log.warning(
                f"[{self.account_name}] bizId={biz_id[:8]}... 已 EXPIRE"
            )
            raise CheckExpireError(f"bizId {biz_id[:8]}... EXPIRE")
        # 兜底:检查 dict 字段
        if isinstance(raw, dict):
            if raw.get("status") == "EXPIRE" or raw.get("expired"):
                raise CheckExpireError(f"bizId {biz_id[:8]}... EXPIRE")
            return bool(raw.get("valid", True))
        return True

    async def create_order(
        self,
        plan: PlanPreview,
        *,
        biz_id: str = "",
        require_biz_id: bool = False,
    ) -> OrderResult:
        """创建订单。

        ⚠️ 下单接口的真实参数需在补货后抓包确认。当前按已知字段构造,
        字段名做了多别名兜底;如果平台校验严格,补货后可能需要调整。

        Args:
            plan: 目标套餐(batch-preview 模式返回的 PlanPreview)。
            biz_id: qtaxm 模式下由 :meth:`preview_single` 返回的 bizId。
                   传空字符串表示 batch-preview 模式(不带 bizId)。
            require_biz_id: 为 True 且 biz_id 为空时,抛 :class:`ValueError`。
                          默认 False 保持向后兼容。**qtaxm 链路应在调用前已确保 biz_id 非空**。

        tier/period 取自实际选中的 plan(多套餐降级时可能不是 config 的默认值)。
        """
        if require_biz_id and not biz_id:
            raise ValueError(
                "create_order: require_biz_id=True 但 biz_id 为空。"
                "请先调用 preview_single 拿到 bizId,或使用 batch-preview 模式。"
            )

        payload = {
            "productId": plan.product_id,
            "subscribeMode": SUBSCRIBE_MODE_CONTINUOUS,
            "subscribePeriod": plan.period or BILLING_CYCLE_CODE[self.config.billing_cycle.value],
            "tier": plan.tier,
            "payChannel": PAY_CHANNEL_CODE[self.config.pay_channel.value],
            "usePinhaomo": self.config.use_pinhaomo,
            "payAmount": plan.pay_amount,
        }
        if biz_id:
            payload["bizId"] = biz_id
        else:
            log.debug(
                f"[{self.account_name}] create_order 不带 bizId(batch-preview 模式)"
            )

        data = await with_retry(
            lambda: self.client.request(
                "POST", PATH_CREATE_BANK_ORDER, json=payload
            ),
            **self._retry_kwargs("createBankOrder"),
        )
        d = _extract_data(data)
        order_id = str(
            d.get("orderNo")
            or d.get("orderId")
            or d.get("subscriptionNo")
            or ""
        )
        biz_id_returned = str(d.get("bizId") or biz_id)
        pay_url = str(d.get("payUrl") or d.get("payLink") or "")
        status = str(d.get("paymentStatus") or d.get("status") or "WAIT_PAY")
        result = OrderResult(
            order_id=order_id, biz_id=biz_id_returned,
            pay_url=pay_url, status=status, raw=d,
        )
        log.info(
            f"[{self.account_name}] 下单成功: orderNo={order_id} status={status}"
        )
        return result

    # ----------------------------------------------------------- 整链路

    async def run_purchase_chain(self) -> OrderResult:
        """执行完整下单链路。单账号串行，避免触发风控。

        多套餐降级：按 config.target_plans 优先级（如 [Max, Pro]）依次尝试，
        第一个非售罄的套餐即下单。
        """
        # 1. 客户信息 + 登录态
        customer = await self.get_customer_info()
        if not customer.user_id:
            raise AuthError("getCustomerInfo 未返回有效 id，登录态失效")

        # 2. 批量预览（拿全部套餐 + 售罄状态）
        preview = await self.batch_preview()

        # 3. 按优先级挑第一个可买的套餐
        plan = self.pick_best_available(preview)

        # 4. 下单
        order = await self.create_order(plan)
        # 把实际选中的套餐信息附到 order 上，便于通知展示
        order.raw["_selected_tier"] = plan.tier
        order.raw["_selected_period"] = plan.period
        order.raw["_selected_pay_amount"] = plan.pay_amount
        return order

    async def run_preview_check_chain(
        self, *, max_expire_retries: int = 5
    ) -> OrderResult:
        """qtaxm/glm-rush 模式:preview + check 双重校验 + EXPIRE 自动重试。

        流程:
          1. getCustomerInfo 验证登录态
          2. 按优先级对 target_plans 每个套餐尝试 preview_single
             - 售罄(bizId=null)→ 降级到下一个
             - 拿到 bizId → check
               - check 通过 → create_order → 返回
               - check EXPIRE → 立即重试 preview,直到拿到可用的
          3. 任一档位成功后,create_order + 返回

        Returns:
            OrderResult 带有 biz_id 字段。

        Raises:
            SoldOutError: 所有候选档位都 preview 售罄。
            AuthError: 登录态失效。
        """
        # 1. 登录态
        customer = await self.get_customer_info()
        if not customer.user_id:
            raise AuthError("getCustomerInfo 未返回有效 id,登录态失效")

        # 2. 按优先级挑第一个能 preview 出 bizId 的套餐
        for plan_enum in self.config.target_plans:
            tier = PLAN_TIER_CODE[plan_enum.value]
            period = BILLING_CYCLE_CODE[self.config.billing_cycle.value]

            for attempt in range(1, max_expire_retries + 1):
                try:
                    preview_data = await self.preview_single(tier, period)
                except ApiError as e:
                    log.warning(
                        f"[{self.account_name}] preview tier={tier} 失败: {e},尝试下一档"
                    )
                    break   # 这种是结构性错误(无 productId / 接口变了),换下一档

                if preview_data is None:
                    # 售罄,换下一档
                    log.info(
                        f"[{self.account_name}] preview tier={tier} 售罄,尝试下一档"
                    )
                    break

                biz_id = str(preview_data.get("bizId") or "")
                if not biz_id:
                    log.warning(
                        f"[{self.account_name}] preview 返回 bizId 异常: {preview_data}"
                    )
                    continue

                # 3. check 校验
                try:
                    ok = await self.check_biz_id(biz_id)
                except CheckExpireError:
                    log.warning(
                        f"[{self.account_name}] bizId={biz_id[:8]}... EXPIRE,"
                        f"第 {attempt}/{max_expire_retries} 次重试"
                    )
                    continue  # 立即重试 preview

                if not ok:
                    log.warning(
                        f"[{self.account_name}] check bizId={biz_id[:8]}... 失败,重试"
                    )
                    continue

                # 4. check 通过 → 下单
                # 构造 PlanPreview 用于 create_order
                fake_plan = PlanPreview(
                    product_id=PRODUCT_ID_REFERENCE.get((tier, period), ""),
                    tier=tier, period=period,
                    sold_out=False, can_purchase=True,
                    pay_amount=float(preview_data.get("payAmount") or 0),
                    original_amount=float(preview_data.get("originalAmount") or 0),
                )
                order = await self.create_order(
                    fake_plan, biz_id=biz_id, require_biz_id=True,
                )
                order.raw["_selected_tier"] = tier
                order.raw["_selected_period"] = period
                order.raw["_selected_pay_amount"] = fake_plan.pay_amount
                log.success(
                    f"[{self.account_name}] preview+check+grab 成功: "
                    f"orderNo={order.order_id} bizId={biz_id[:8]}..."
                )
                return order

            # 这个 tier 试完 max_expire_retries 都 EXPIRE 或售罄,换下一档
        # 全部失败
        raise SoldOutError(
            f"preview_check 全部档位售罄或持续 EXPIRE: {[p.value for p in self.config.target_plans]}"
        )

    # ----------------------------------------------------------- 便捷：查待支付订单

    async def list_pending_orders(self) -> list[dict[str, Any]]:
        """查询当前待支付订单（真实接口：orders/pending）。"""
        data = await with_retry(
            lambda: self.client.request("GET", PATH_ORDERS_PENDING),
            **self._retry_kwargs("orders/pending"),
        )
        d = _extract_data(data)
        items = d if isinstance(d, list) else []
        return [x for x in items if isinstance(x, dict)]


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _extract_data(resp: Any) -> dict[str, Any]:
    """从返回体里抽出 data 字段。

    真实结构：{ "code": 200, "msg": "...", "data": {...}, "success": true }
    """
    if isinstance(resp, dict):
        if "data" in resp and resp.get("data") is not None:
            inner = resp["data"]
            if isinstance(inner, (dict, list)):
                return inner
            return {"_data": inner}
        return resp
    return {"_raw": resp}


def _parse_plan(item: dict[str, Any]) -> PlanPreview:
    """解析 batch-preview 里单个套餐。

    真实响应里 tier / subscribePeriod 字段常常为空，所以：
    1. 优先用响应里的 tier / subscribePeriod
    2. 否则用 monthlyOriginalAmount 推 tier
    3. 用 campaignDiscountDetails.campaignName（连续包月/季/年）推 period
    4. 都推不出来再用 PRODUCT_ID_REFERENCE 兜底
    """
    product_id = str(item.get("productId") or "")
    tier = str(item.get("tier") or "")
    period = str(item.get("subscribePeriod") or item.get("period") or "")

    if not tier:
        tier = _infer_tier_by_price(item) or ""
    if not period:
        period = _infer_period_by_campaign(item) or ""

    # 仍为空 → 用 productId 反查参考表
    if (not tier or not period) and product_id:
        for (ref_tier, ref_period), ref_id in PRODUCT_ID_REFERENCE.items():
            if ref_id == product_id:
                tier = tier or ref_tier
                period = period or ref_period
                break

    return PlanPreview(
        product_id=product_id,
        tier=tier,
        period=period,
        sold_out=bool(item.get(FIELD_SOLD_OUT, False)),
        can_purchase=_nullable_bool(item.get(FIELD_CAN_PURCHASE)),
        pay_amount=_to_yuan(item.get("payAmount") or item.get("monthlyPayAmount")),
        original_amount=_to_yuan(
            item.get("originalAmount") or item.get("monthlyOriginalAmount")
        ),
        raw=item,
    )


def _infer_tier_by_price(item: dict[str, Any]) -> Optional[str]:
    """用 monthlyOriginalAmount 推 tier：49=LITE / 149=PRO / 469=MAX。"""
    monthly = item.get("monthlyOriginalAmount")
    if monthly is None:
        monthly = item.get("originalAmount")
    if monthly is None:
        return None
    try:
        m = float(monthly)
    except (TypeError, ValueError):
        return None
    return TIER_BY_MONTHLY_PRICE.get(m)


def _infer_period_by_campaign(item: dict[str, Any]) -> Optional[str]:
    """用 campaignName（连续包月/季/年）推 period。

    若无周期优惠（只有"拼好模"），按月原价==原价 判定为连续包月。
    """
    camps = item.get("campaignDiscountDetails") or []
    if isinstance(camps, list):
        for cm in camps:
            if not isinstance(cm, dict):
                continue
            name = str(cm.get("campaignName") or "")
            for kw, period in PERIOD_BY_CAMPAIGN_KEYWORD.items():
                if kw in name:
                    return period
    # 兜底：月原价 == 原价（即非多年打包）→ 连续包月
    try:
        monthly = float(item.get("monthlyOriginalAmount") or 0)
        orig = float(item.get("originalAmount") or 0)
    except (TypeError, ValueError):
        return None
    if monthly > 0 and orig > 0 and abs(monthly - orig) < 0.01:
        return "MONTHLY"
    return None


def _nullable_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return None


def _to_yuan(v: Any) -> float:
    """真实接口金额单位是「元」（如 598.0），直接转 float。"""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
