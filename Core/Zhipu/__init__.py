"""Zhipu (bigmodel.cn) GLM Coding 套餐抢购模块.

把 References/GlmCodingGrabber 的业务实现吸收进 WebAuto,共享项目内
TimeSync / Errors / Fetchers 等基础能力。

使用示例:

    from Core.Zhipu import ApiClient, BigModelApi
    from Core.Zhipu.config import AppConfig, Account

    cfg = AppConfig(
        accounts=[Account(name='main', phone='138xxxxxxxx', token='your-token')],
        target_plan='Max',
        billing_cycle='yearly',
        pay_channel='alipay',
    )
    client = ApiClient(cfg, token='your-token', account_name='main')
    api = BigModelApi(client, cfg)
    result = await api.run_purchase_chain()

如果需要完整 CLI:

    python -m Core.Zhipu grab -c config.yaml
    python -m Core.Zhipu check
    python -m Core.Zhipu sync
"""

__version__ = "1.0.0"

from .constants import (
    BASE_URL,
    API_BASE,
    PATH_BATCH_PREVIEW,
    PATH_PREVIEW,
    PATH_CHECK,
    PATH_CREATE_BANK_ORDER,
    PATH_CUSTOMER_INFO,
    PATH_PRICING,
    PRODUCT_ID_REFERENCE,
    PLAN_TIER_CODE,
    BILLING_CYCLE_CODE,
)
from .exceptions import (
    ZhipuError,
    NetworkError,
    RateLimitedError,
    AuthError,
    SoldOutError,
    CheckExpireError,
    RiskBlockedError,
    ApiError,
    RetryableError,
)
from .http_client import ApiClient, with_retry, build_default_headers
from .api import BigModelApi, CustomerInfo, PlanPreview, PreviewResult, OrderResult
from .config import AppConfig, Account, AdaptiveRetryPolicy, load_config
from .session import Session, SessionManager
from .scheduler import GrabScheduler, GrabSummary, compute_slow_delay_s
from .orchestrator import Orchestrator

__all__ = [
    # 常量
    "BASE_URL", "API_BASE",
    "PATH_BATCH_PREVIEW", "PATH_PREVIEW", "PATH_CHECK",
    "PATH_CREATE_BANK_ORDER", "PATH_CUSTOMER_INFO",
    "PRODUCT_ID_REFERENCE", "PLAN_TIER_CODE", "BILLING_CYCLE_CODE",
    # 异常
    "ZhipuError", "NetworkError", "RateLimitedError", "AuthError",
    "SoldOutError", "CheckExpireError", "RiskBlockedError", "ApiError", "RetryableError",
    # 客户端
    "ApiClient", "with_retry", "build_default_headers",
    # API
    "BigModelApi", "CustomerInfo", "PlanPreview", "PreviewResult", "OrderResult",
    # 配置与会话
    "AppConfig", "Account", "AdaptiveRetryPolicy", "load_config",
    "Session", "SessionManager",
    # 调度与编排
    "GrabScheduler", "GrabSummary", "Orchestrator", "compute_slow_delay_s",
]
