"""平台常量定义.

集中维护 URL、接口路径、套餐/计费/支付映射等，避免散落在各处。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 平台基础
# ---------------------------------------------------------------------------

BASE_URL = "https://bigmodel.cn"
API_BASE = "https://bigmodel.cn"
REFERER_GLM_CODING = f"{BASE_URL}/glm-coding"
REFERER_SUBSCRIBE_PAY = f"{BASE_URL}/subscribe-pay"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# 接口路径
# ---------------------------------------------------------------------------

# 核心
PATH_LOGIN = "/auth/login"
PATH_CUSTOMER_INFO = "/api/biz/customer/getCustomerInfo"
PATH_SUBSCRIPTION_LIST = "/api/biz/subscription/list"
PATH_PRODUCT_ID_INFO = "/api/biz/tokenResPack/productIdInfo"
PATH_IS_LIMIT_BUY = "/api/biz/tokenAccounts/isLimitBuy"
PATH_BATCH_PREVIEW = "/api/biz/pay/batch-preview"
# 单次预览(从 qtaxm/glm-rush 实测):返回 bizId + 价格,可立即 check
PATH_PREVIEW = "/api/biz/pay/preview"
# bizId 有效性校验(下单后必须 check,EXPIRE 表示已失效需重试)
PATH_CHECK = "/api/biz/pay/check"
PATH_CREATE_BANK_ORDER = "/api/biz/pay/bank/createBankOrder"
# 待支付订单查询（真实抓包确认）
PATH_ORDERS_PENDING = "/api/biz/subscription/enterprise/v2/orders/pending"
# 个人版定价表
PATH_PRICING = "/api/biz/subscription/enterprise/v2/pricing"

# 辅助
PATH_RISK_INFO = "/api/biz/customer/risk/info"
# 历史路径(已下线):智谱没有开放短信登录 API,
# 抢购链路发现 token 失效必须由用户在浏览器里手动登录后回填凭证,
# 不要再尝试用 httpx 调这两条路径。
# (旧) PATH_SMS_CODE = "/api/biz/code/smsCode/{phone}"
# (旧) PATH_CHECK_SMS_CODE = "/api/biz/code/checkSmsCode/{code}"
PATH_OPERATION_QUERY = "/api/biz/operation/query"

# ---------------------------------------------------------------------------
# 业务参数映射
# ---------------------------------------------------------------------------

# 套餐档位 → 后端 tier 枚举（真实抓包确认，来自 pricing 接口的 tier 字段）
PLAN_TIER_CODE = {
    "Lite": "LITE",
    "Pro": "PRO",
    "Max": "MAX",
}

# 计费周期 → 后端枚举（真实抓包确认，来自 pricing 接口的 subscribePeriod 字段）
BILLING_CYCLE_CODE = {
    "monthly": "MONTHLY",
    "quarterly": "QUARTERLY",
    "yearly": "YEARLY",
}

# 计费模式：连续订阅
SUBSCRIBE_MODE_CONTINUOUS = "CONTINUOUS"

# 支付渠道 → 后端枚举值
PAY_CHANNEL_CODE = {
    "alipay": "alipay",
    "weChat_pay": "weChat_pay",
    "balance_pay": "balance_pay",
    "public_pay": "public_pay",
}

# ---------------------------------------------------------------------------
# 真实抓包得到的 productId 映射（2026-06-17 抓包确认）
# 来源：POST /api/biz/pay/batch-preview 响应。
# batch-preview 的 tier/period 字段为空，需通过 monthlyOriginalAmount 推 tier、
# 通过 campaignDiscountDetails.campaignName（连续包月/季/年）推 period。
# 下表为兜底用，脚本运行时优先用价格+优惠动态匹配。
# ---------------------------------------------------------------------------
# 月原价 → tier
TIER_BY_MONTHLY_PRICE = {
    49.0: "LITE",
    149.0: "PRO",
    469.0: "MAX",
}

# campaignName 关键词 → period
PERIOD_BY_CAMPAIGN_KEYWORD = {
    "连续包月": "MONTHLY",
    "连续包季": "QUARTERLY",
    "连续包年": "YEARLY",
}

# (tier, period) -> productId（价格+优惠匹配不上时的兜底）
PRODUCT_ID_REFERENCE = {
    ("LITE", "MONTHLY"): "product-02434c",
    ("LITE", "QUARTERLY"): "product-b8ea38",
    ("LITE", "YEARLY"): "product-70a804",
    ("PRO", "MONTHLY"): "product-1df3e1",
    ("PRO", "QUARTERLY"): "product-fef82f",
    ("PRO", "YEARLY"): "product-5643e6",
    ("MAX", "MONTHLY"): "product-2fc421",
    ("MAX", "QUARTERLY"): "product-5d3a03",
    ("MAX", "YEARLY"): "product-d46f8b",
}



# ---------------------------------------------------------------------------
# 状态码 / 错误码（多信号风控识别）
# ---------------------------------------------------------------------------

# 业务返回体结构：{ "code": 200, "msg": "操作成功", "data": ..., "success": true }
CODE_SUCCESS = 200

# 业务码：code != 200 即为错误。常见分类
CODE_NEED_LOGIN = 401       # 登录态失效
# 风控拦截可能用多个业务码,这里列已知 + 推测:
CODE_RISK_BLOCK_CODES = frozenset({
    4030, 4031, 403,         # 已知/推测的风控业务码
    429,                     # 持续限流也可能是风控
})
# 限购/限流业务码(下单接口可能返回,售罄一般在 batch-preview 的 soldOut 字段判断)
CODE_LIMIT_BUY_CODES = frozenset({4001, 4002})

# 单次请求层风控识别关键字(msg 字段包含以下任一即视为风控)
RISK_MSG_KEYWORDS = (
    "风控", "访问频繁", "操作过于频繁", "请稍后再试",
    "risk", "blocked", "too many", "frequent",
)

# 售罄：真实接口不是用错误码，而是 batch-preview 响应里每个套餐的
# "soldOut": true 字段表示售罄；"canPurchase": false 表示不可购买。
FIELD_SOLD_OUT = "soldOut"
FIELD_CAN_PURCHASE = "canPurchase"
FIELD_FORBIDDEN = "forbidden"

# HTTP 限流
HTTP_TOO_MANY_REQUESTS = 429

