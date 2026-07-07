"""HTTP 客户端封装.

基于 httpx.AsyncClient，启用 HTTP/2、连接池复用、统一 Headers，
并把常见的错误（超时、429、5xx、业务码）翻译成 :mod:`grabber.exceptions` 里的
异常，便于上层用重试装饰器统一处理。
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping, Optional

import httpx

from Core.Zhipu.config import AppConfig
from Core.Zhipu.constants import (
    API_BASE,
    CODE_NEED_LOGIN,
    CODE_RISK_BLOCK_CODES,
    CODE_LIMIT_BUY_CODES,
    CODE_SUCCESS,
    DEFAULT_UA,
    HTTP_TOO_MANY_REQUESTS,
    REFERER_GLM_CODING,
    RISK_MSG_KEYWORDS,
)
from Core.Zhipu.exceptions import (
    ApiError,
    AuthError,
    NetworkError,
    RateLimitedError,
    RetryableError,
    RiskBlockedError,
    SoldOutError,
)
from Core.Zhipu.logger import get_logger

log = get_logger()


def build_default_headers(
    *,
    token: Optional[str] = None,
    cookie: Optional[str] = None,
    referer: str = REFERER_GLM_CODING,
) -> dict[str, str]:
    """构造浏览器级别的请求头。"""
    headers: dict[str, str] = {
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
        "Origin": API_BASE,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cookie:
        headers["Cookie"] = cookie
    return headers


class ApiClient:
    """异步 API 客户端。

    一个 :class:`ApiClient` 实例对应一个账号会话。持有 httpx 连接池，
    便于在抢购瞬间复用已建立的 TLS 会话（0-RTT / 已握手连接），降低延迟。
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        token: Optional[str] = None,
        cookie: Optional[str] = None,
        account_name: str = "default",
    ) -> None:
        self.config = config
        self.account_name = account_name
        self._token = token
        self._cookie = cookie
        # 最近一次响应里的 set-cookie 列表(每次 request 会被覆盖)
        # 用于短信重登时拿到服务器下发的最新 cookie。
        # httpx 默认不自动持久化 set-cookie,需要我们自己从响应头抽取。
        self._last_set_cookies: list[str] = []

        limits = httpx.Limits(
            max_keepalive_connections=10,
            max_connections=20,
            keepalive_expiry=30.0,
        )
        transport = httpx.AsyncHTTPTransport(
            http2=True, retries=0, verify=True
        )
        proxy = config.proxy or None

        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            headers=build_default_headers(token=token, cookie=cookie),
            timeout=httpx.Timeout(config.request_timeout_s, connect=5.0),
            limits=limits,
            transport=transport,
            proxy=proxy,
            follow_redirects=False,
        )

    # ------------------------------------------------------------------ 生命周期

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ApiClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ 凭证更新

    def update_credentials(
        self, *, token: Optional[str] = None, cookie: Optional[str] = None
    ) -> None:
        """热更新 token / cookie（例如重新登录后）。"""
        if token is not None:
            self._token = token
            self._client.headers["Authorization"] = f"Bearer {token}"
        if cookie is not None:
            self._cookie = cookie
            self._client.headers["Cookie"] = cookie

    # ------------------------------------------------------------------ 预热

    async def preheat(self) -> None:
        """预热连接：发起一次轻量请求，触发 TLS 握手与连接池建立。

        使用主页或静态资源 GET，即使 404 也能完成握手。
        """
        try:
            # 直接访问 API base 域名根路径以建立连接
            await self._client.get("/", timeout=5.0)
        except httpx.HTTPError as e:
            log.debug(f"[{self.account_name}] 预热请求异常（可忽略）: {e}")

    # ------------------------------------------------------------------ 请求核心

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        parse_json: bool = True,
    ) -> Any:
        """发起一次请求并翻译异常。

        Returns:
            若 ``parse_json`` 为 True，返回解析后的 JSON 体（通常是 dict）；
            否则返回原始 :class:`httpx.Response`。
        """
        to = httpx.Timeout(timeout) if timeout else None
        try:
            resp = await self._client.request(
                method,
                path,
                params=params,
                json=json,
                headers=headers,
                timeout=to,
            )
        except httpx.TimeoutException as e:
            raise NetworkError(f"请求超时: {method} {path} -> {e}") from e
        except httpx.TransportError as e:
            raise NetworkError(f"网络错误: {method} {path} -> {e}") from e
        except httpx.HTTPError as e:
            raise NetworkError(f"HTTP 错误: {method} {path} -> {e}") from e

        # 捕获 set-cookie,供短信重登后拿新凭证
        # httpx.headers 是区分大小写的 dict-like,get_list 取所有匹配项
        self._last_set_cookies = list(resp.headers.get_list("set-cookie"))

        # 限流
        if resp.status_code == HTTP_TOO_MANY_REQUESTS:
            retry_after = _parse_retry_after(resp)
            raise RateLimitedError(retry_after_ms=retry_after)

        # 5xx 视为可重试
        if 500 <= resp.status_code < 600:
            raise RetryableError(
                f"服务端 {resp.status_code}: {method} {path}"
            )

        if not parse_json:
            return resp

        # 解析 JSON
        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            # 某些接口（如 createBankOrder）可能返回非 JSON，原样返回文本
            text = (resp.text or "")[:500]
            if resp.is_success:
                log.debug(
                    f"[{self.account_name}] {method} {path} 返回非 JSON: {text!r}"
                )
                return {"_raw": text, "status_code": resp.status_code}
            raise ApiError(
                f"响应解析失败 ({resp.status_code}): {text!r}",
                code=resp.status_code,
                payload=text,
            ) from e

        # 业务码翻译
        _translate_business_code(data, resp.status_code, method, path)
        return data


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _parse_retry_after(resp: httpx.Response) -> int:
    """从 429 响应里解析 Retry-After(秒),转成毫秒。默认 2s。"""
    ra = resp.headers.get("Retry-After")
    if not ra:
        return 2000
    try:
        return int(float(ra) * 1000)
    except ValueError:
        return 2000


def set_cookies_to_cookie_string(set_cookies: list[str]) -> str:
    """把 set-cookie header 列表合并成可放到 Cookie header 里的字符串。

    set-cookie 形如 ``sid=abc; Path=/; HttpOnly``,我们只取 ``name=value`` 部分,
    用 ``; `` 拼接,得到 ``sid=abc; tok=def``。

    Args:
        set_cookies: 原始 set-cookie 字符串列表(可为空)。

    Returns:
        可作为 Cookie header 的字符串;空列表返回 ""。
    """
    pairs: list[str] = []
    for sc in set_cookies:
        # 第一个 ``;`` 之前是 ``name=value``
        first = sc.split(";", 1)[0].strip()
        if "=" in first:
            pairs.append(first)
    return "; ".join(pairs)


def _translate_business_code(
    data: Any, status: int, method: str, path: str
) -> None:
    """根据返回体里的 code 字段 + msg 关键字 + HTTP 状态多信号识别异常。

    识别策略(优先级从高到低):
      1. 业务 code == 401 / 状态 401 → AuthError
      2. 业务 code 在 CODE_RISK_BLOCK_CODES / 状态 403 / msg 含风控关键字
         → RiskBlockedError
      3. 业务 code 在 CODE_LIMIT_BUY_CODES → SoldOutError
      4. 其他业务错误 → ApiError
    """
    if not isinstance(data, Mapping):
        return
    code = data.get("code")
    msg = str(data.get("msg") or data.get("message") or "")

    if code is None:
        # 没有统一 code 字段的接口,按 HTTP 状态判断
        if status >= 400:
            raise ApiError(
                f"HTTP {status}: {method} {path}", code=status, payload=data
            )
        return

    if code == CODE_SUCCESS:
        return

    # 1. 登录态失效
    if code == CODE_NEED_LOGIN or status == 401:
        raise AuthError(f"未登录或登录态失效: {msg} (code={code})")

    # 2. 风控拦截(多信号:业务码 / HTTP 状态 / msg 关键字)
    if (
        code in CODE_RISK_BLOCK_CODES
        or status == 403
        or any(kw.lower() in msg.lower() for kw in RISK_MSG_KEYWORDS)
    ):
        raise RiskBlockedError(
            f"被风控拦截: {msg} (code={code} status={status})"
        )

    # 3. 限购(下单接口可能返回)
    if code in CODE_LIMIT_BUY_CODES:
        raise SoldOutError(f"售罄/限购: {msg} (code={code})")

    # 4. 其余业务错误
    raise ApiError(f"{msg} (code={code})", code=code, payload=data)


# ---------------------------------------------------------------------------
# 重试装饰器
# ---------------------------------------------------------------------------


async def with_retry(
    coro_factory,
    *,
    times: int,
    delay_ms: int,
    backoff_factor: float,
    on_429_wait_ms: int,
    account_name: str = "default",
    op_desc: str = "请求",
):
    """对一次可重试操作执行指数退避重试。

    Args:
        coro_factory: 无参函数，每次调用返回一个新的协程。
        times: 最大尝试次数（含首次）。
        delay_ms: 初始延迟毫秒。
        backoff_factor: 指数退避因子。
        on_429_wait_ms: 命中限流时的额外等待毫秒。
        account_name: 用于日志。
        op_desc: 操作描述，用于日志。
    """
    last_exc: Optional[Exception] = None
    delay = delay_ms / 1000.0
    for attempt in range(1, times + 1):
        try:
            return await coro_factory()
        except RateLimitedError as e:
            last_exc = e
            wait = (e.retry_after_ms or on_429_wait_ms) / 1000.0
            log.warning(
                f"[{account_name}] {op_desc} 命中限流，第 {attempt}/{times} 次，"
                f"等待 {wait:.2f}s 后重试"
            )
            await asyncio.sleep(wait)
        except (NetworkError, RetryableError) as e:
            last_exc = e
            log.warning(
                f"[{account_name}] {op_desc} 网络错误，第 {attempt}/{times} 次: {e}，"
                f"{delay:.2f}s 后重试"
            )
            await asyncio.sleep(delay)
            delay *= backoff_factor
        except (AuthError, SoldOutError, RiskBlockedError):
            # 这些错误重试无意义，直接上抛
            raise
        except ApiError as e:
            # 业务错误：若剩余次数足够，按退避重试一次（接口可能瞬时抖动）
            last_exc = e
            if attempt >= times:
                raise
            log.warning(
                f"[{account_name}] {op_desc} 业务错误，第 {attempt}/{times} 次: "
                f"{e}，{delay:.2f}s 后重试"
            )
            await asyncio.sleep(delay)
            delay *= backoff_factor
    # 理论不可达
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{op_desc} 重试耗尽")
