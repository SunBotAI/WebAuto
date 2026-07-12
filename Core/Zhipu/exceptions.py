"""Zhipu 套餐抢购异常体系.

继承自 Core.Errors.WebAutoError,这样 WebAuto 项目里所有 except WebAutoError
能统一捕获 Zhipu 业务异常。

设计原则:
- 所有异常按"该不该重试"分类
- 携带足够的上下文(code / retry_after / payload)便于上层决策
- 永远继承 ZhipuError(WebAutoError),保证 except WebAutoError 兜底
"""
from __future__ import annotations

from typing import Any, Optional

from Core.Errors import WebAutoError


class ZhipuError(WebAutoError):
    """Zhipu 子包异常基类。

    继承自 WebAutoError,可以:
      - except WebAutoError: 兜底所有 WebAuto 相关异常
      - except ZhipuError: 只处理 Zhipu 业务异常
    """


class NetworkError(ZhipuError):
    """网络层错误:连接失败、超时、TLS 握手错误等。

    **可重试**。with_retry 会自动退避重试,通常重试 2-3 次可恢复。
    触发示例:本地网络抖动、智谱服务端临时 502、连接被防火墙重置。
    """


class RateLimitedError(ZhipuError):
    """命中 HTTP 429 限流。需等待 Retry-After 秒后重试。

    **可重试**。with_retry 会读 retry_after_ms 字段决定等待时长。

    Attributes:
        retry_after_ms: 429 响应头 Retry-After 解析出的毫秒数。
                       若响应头无该字段,使用传入的默认值(通常 2000ms)。
    """

    def __init__(self, message: str = "命中限流(429)", *, retry_after_ms: int = 0):
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


class AuthError(ZhipuError):
    """登录态失效或未授权(code=401 / 4031 等)。

    **不重试**。重试毫无意义,必须重新登录。处理方式:
      - 抢购主流程会自动跳过失效账号并继续;用户需到浏览器手动登录
        https://bigmodel.cn 后,把新 token/cookie 回填到加密凭证库。
      - 旧的 API 短信重登(relogin_by_sms)已删除:智谱不开放该接口,
        抢购链路不应再尝试 httpx 调用 /api/biz/code/smsCode/* 。
    """


class SoldOutError(ZhipuError):
    """套餐售罄(全部档位都不可买)。

    **不重试**。qtaxm 模式下,单个档位售罄会降级到下一档(target_plans 列表),
    只有所有档位都售罄才抛这个错。抛出后整次抢购结束。
    """


class CheckExpireError(ZhipuError):
    """bizId check 返回 EXPIRE。

    **可立即重试**。触发场景:抢到了下单,但该 bizId 已被别人用掉,
    check 接口返回 data="EXPIRE"。

    重要:这种错误**应该立即重新发起 preview,不需要等**——因为 EXPIRE 通常是
    "有人同时抢到了同一档位"导致的,立即重试有可能抢到新的 bizId。
    间隔 0ms 的 burst 阶段就是为了应对这种情况。
    """


class RiskBlockedError(ZhipuError):
    """被智谱风控拦截(code=403 / 持续 429 / 业务码 4030 / 文本含"风控"等)。

    **不重试**。重试只会加重风控。处理方式:
      1. 立即停止当前账号
      2. 等待几小时或换 IP / 换账号
      3. 或切换到 browser.py 备用方案(模拟真实浏览器可能能绕过)
    """


class ApiError(ZhipuError):
    """业务接口返回了非成功状态,既不是网络错也不是已知分类。

    可能是临时 5xx、字段解析失败、业务返回码未知等。with_retry 会按退避策略
    短暂重试,达到重试上限后上抛。

    Attributes:
        code: 业务返回码(如果有)。
        payload: 原始返回体(脱敏前),用于排查问题时打印。
    """

    def __init__(
        self,
        message: str,
        *,
        code: Optional[int] = None,
        payload: Any = None,
    ):
        super().__init__(message)
        self.code = code
        self.payload = payload


class RetryableError(ZhipuError):
    """其他可重试的业务错误:临时 5xx、偶发空响应、JSON 解析失败等。

    **可重试**。与 NetworkError 行为相同,分类独立是为了日志能区分来源。
    """
