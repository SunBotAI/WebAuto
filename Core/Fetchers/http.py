"""
纯 HTTP 获取器
使用 curl_cffi,支持 TLS 指纹模拟(impersonate chrome/firefox 等)
速度最快, TLS 指纹可通过 sannysoft 等检测
"""
from typing import Optional, Dict, Any, List
import curl_cffi
from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import Timeout  # CurlError is in curl_cffi directly
from lxml import html

from .base import BaseFetcher, FetcherMode, FetcherResponse


# ===== curl_cffi BrowserType 别名映射 =====
# 用于 config.fingerprint 字符串 → BrowserType 转换
_IMPERSONATE_MAP: Dict[str, str] = {
    "chrome120": "chrome120",
    "chrome124": "chrome124",
    "chrome123": "chrome123",
    "chrome131": "chrome131",
    "firefox120": "firefox133",   # firefox120 在 curl_cffi 0.15 中映射到 firefox133
    "firefox133": "firefox133",
    "edge101":   "edge101",
}

# ===== 浏览器伪装:Chrome 120 的标准 header 顺序 =====
# curl_cffi 在 impersonate 模式下自动设置 TLS/ALPN/H2 等指纹,
# 但 HTTP headers 仍需手动按 Chrome 顺序填充,以绕过 Header 顺序检测.
_CHROME_HEADER_ORDER = [
    "Host",
    "Connection",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "Upgrade-Insecure-Requests",
    "User-Agent",
    "Accept",
    "Sec-Fetch-Site",
    "Sec-Fetch-Mode",
    "Sec-Fetch-User",
    "Sec-Fetch-Dest",
    "Accept-Encoding",
    "Accept-Language",
    "Cookie",
]


def _normalize_headers(headers: dict) -> "list[tuple[str, str]]":
    """把 headers dict 转成 **有序** 的 list of (k, v) 元组.

    顺序: 按 _CHROME_HEADER_ORDER 出现顺序排,其他未知的 header 放最后(保持相对顺序).
    curl_cffi.requests.AsyncSession 支持 headers=[(k,v), ...] 这种 list 形式,
    会按 list 顺序发出,与 Chrome 真实请求顺序一致.
    """
    by_key = {k.lower(): (k, v) for k, v in headers.items()}
    seen = set()
    out = []
    for k in _CHROME_HEADER_ORDER:
        pair = by_key.get(k.lower())
        if pair:
            out.append(pair)
            seen.add(pair[0].lower())
    # 兜底:其他 header 放最后
    for k_low, pair in by_key.items():
        if k_low not in seen:
            out.append(pair)
            seen.add(k_low)
    return out


from Core.Errors import (
    FetcherInitError,
    FetcherNetworkError,
    FetcherTimeoutError,
    ElementNotFoundError,
)


class HttpFetcher(BaseFetcher):
    """纯 HTTP 模式获取器,速度最快,支持 TLS 指纹模拟.

    使用 curl_cffi.requests.AsyncSession 的 impersonate 功能,
    自动模拟 chrome/firefox 等浏览器的 TLS 指纹 (JA3/JA4),
    可过 sannysoft 等 TLS 指纹检测.
    """

    mode = FetcherMode.HTTP

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._session: Optional["curl_requests.AsyncSession"] = None
        self._cookies: Dict[str, str] = {}
        self._proxy: Optional[str] = None
        self._last_response: Optional[FetcherResponse] = None
        self._last_dom: Optional[html.HtmlElement] = None

    async def init(self) -> None:
        """初始化 HTTP 客户端(curl_cffi impersonate session)"""
        try:
            timeout = self.config.get("timeout", 30)
            follow_redirects = self.config.get("follow_redirects", True)

            # === TLS 指纹 impersonate 模式 ===
            # 优先级: config.fingerprint > config.impersonate > 兜底 chrome120
            fingerprint: str = self.config.get(
                "fingerprint",
                self.config.get("impersonate", "chrome120")
            )
            impersonate = _IMPERSONATE_MAP.get(fingerprint, "chrome120")

            # 在 impersonate 模式下,UA 等 headers 会由 curl_cffi 自动设置,
            # 但仍允许 config.headers 覆盖,以及 Profile 对象进一步自定义.
            headers_dict: Dict[str, str] = {}

            # 先接 Profile(如果传了 browser_profile_id)
            profile_obj = None
            try:
                from Core.BrowserProfile import ProfileStore
                pid = self.config.get("browser_profile_id")
                if pid:
                    profile_obj = ProfileStore().get_or_create(
                        pid,
                        seed=self.config.get("browser_profile_seed"),
                    )
                    for k, v in profile_obj.apply_to_http_headers().items():
                        headers_dict[k] = v
            except Exception as e:
                import warnings
                warnings.warn(f"Profile load skipped: {e}", stacklevel=1)

            # 接 config.headers(允许覆盖默认值)
            extra = self.config.get("headers") or {}
            headers_dict.update({k: v for k, v in extra.items() if v is not None})

            # 在 impersonate 模式下,curl_cffi 会自动设置:
            #   - TLS JA3/JA4 指纹 (chrome120/chrome124/firefox120...)
            #   - HTTP/2 ALPN 指纹
            #   - Sec-CH-UA* 系列 headers
            #   - Default headers for the impersonated browser
            # 所以 headers_dict 主要补充: Accept-Language(curl_cffi 会自动设但允许覆盖) / Cookie 等
            headers_ordered = _normalize_headers(headers_dict)

            # === 构建 curl_cffi AsyncSession ===
            session_kwargs: Dict[str, Any] = {
                "impersonate": impersonate,
                "timeout": timeout,
                "headers": headers_ordered,
                "cookies": self._cookies,
                "max_redirects": 10 if follow_redirects else 0,
            }

            # curl_cffi 支持 proxies 参数(dict or str)
            proxy = self._proxy
            if proxy:
                session_kwargs["proxies"] = proxy

            self._session = curl_requests.AsyncSession(**session_kwargs)
            self._initialized = True
            print(f"[HttpFetcher] Initialized (impersonate={impersonate})")

        except Exception as e:
            raise FetcherInitError(f"HttpFetcher init failed: {e}") from e

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._session:
            await self._session.close()
            self._session = None
        self._initialized = False
        print("[HttpFetcher] Closed")

    async def get(self, url: str, **kwargs) -> FetcherResponse:
        """GET 请求"""
        if not self._session:
            raise FetcherInitError("HttpFetcher not initialized")

        try:
            response = await self._session.get(url, **kwargs)
            return self._build_response(response)
        except Timeout:
            raise FetcherTimeoutError(f"GET {url} timeout") from None
        except curl_cffi.CurlError as e:
            raise FetcherNetworkError(f"GET {url} curl error: {e}") from None
        except Exception as e:
            raise FetcherNetworkError(f"GET {url} failed: {e}") from e

    async def post(
        self,
        url: str,
        data: Any = None,
        json: Any = None,
        **kwargs
    ) -> FetcherResponse:
        """POST 请求"""
        if not self._session:
            raise FetcherInitError("HttpFetcher not initialized")

        try:
            response = await self._session.post(
                url, data=data, json=json, **kwargs
            )
            return self._build_response(response)
        except Timeout:
            raise FetcherTimeoutError(f"POST {url} timeout") from None
        except curl_cffi.CurlError as e:
            raise FetcherNetworkError(f"POST {url} curl error: {e}") from None
        except Exception as e:
            raise FetcherNetworkError(f"POST {url} failed: {e}") from e

    def _build_response(self, response: "curl_requests.Response") -> FetcherResponse:
        """构建统一响应对象"""
        # 解析 DOM
        try:
            dom = html.fromstring(response.text)
        except Exception:
            dom = None

        # curl_cffi Response 对象
        result = FetcherResponse(
            url=str(response.url),
            status=response.status_code,
            headers=dict(response.headers),
            content=response.content,
            text=response.text,
            dom=dom,
        )

        self._last_response = result
        self._last_dom = dom
        return result

    async def find(self, selector: str, **kwargs) -> Optional[html.HtmlElement]:
        """使用 CSS 选择器查找元素"""
        if not self._last_dom or len(self._last_dom) == 0:
            raise ElementNotFoundError("No page loaded yet")

        elements = self._last_dom.cssselect(selector)
        if elements:
            return elements[0]
        return None

    async def find_all(self, selector: str, **kwargs) -> List[html.HtmlElement]:
        """查找所有匹配元素"""
        if not self._last_dom or len(self._last_dom) == 0:
            return []

        return list(self._last_dom.cssselect(selector))

    async def extract(
        self,
        selector: str,
        attribute: Optional[str] = None
    ) -> Optional[str]:
        """提取文本或属性"""
        element = await self.find(selector)
        if element is None:
            return None

        if attribute:
            return element.get(attribute)
        return element.text_content().strip()

    async def click(self, selector: str, **kwargs) -> None:
        """HTTP 模式不支持点击"""
        raise NotImplementedError("HttpFetcher does not support click operation")

    async def type(self, selector: str, text: str, **kwargs) -> None:
        """HTTP 模式不支持输入"""
        raise NotImplementedError("HttpFetcher does not support type operation")

    async def screenshot(self, path: Optional[str] = None, **kwargs) -> bytes:
        """HTTP 模式不支持截图"""
        raise NotImplementedError("HttpFetcher does not support screenshot")

    async def evaluate(self, script: str, *args) -> Any:
        """HTTP 模式不支持 JS 执行"""
        raise NotImplementedError("HttpFetcher does not support evaluate")

    async def wait_for(self, selector: str, **kwargs) -> None:
        """HTTP 模式不支持等待"""
        element = await self.find(selector)
        if element is None:
            raise ElementNotFoundError(f"Element not found: {selector}")

    # ===== 会话管理 =====

    def get_cookies(self) -> Dict[str, str]:
        """获取当前 Cookies"""
        if self._session:
            return dict(self._session.cookies)
        return self._cookies.copy()

    def set_cookies(self, cookies: Dict[str, str]) -> None:
        """设置 Cookies"""
        self._cookies.update(cookies)
        if self._session:
            for k, v in cookies.items():
                self._session.cookies.set(k, v)

    def set_proxy(self, proxy: Optional[str]) -> None:
        """设置代理

        必须在 init() 之前调用才会生效。
        init() 之后修改代理需要重新 init()(close + init)。
        """
        if self._initialized:
            raise RuntimeError(
                "HttpFetcher.set_proxy must be called before init(); "
                "to switch proxy after init, call close() then init() again"
            )
        self._proxy = proxy

    # ===== TLS 指纹池切换 =====
    # 用于动态切换 impersonate 指纹(不影响已有 session,下次请求生效)
    def set_fingerprint(self, fingerprint: str) -> None:
        """设置 TLS 指纹类型(下次 init 时生效)。

        支持: chrome120, chrome124, chrome123, chrome131, firefox120, firefox133, edge101
        必须在 init() 之前调用,否则需要 close() 再 init().

        Args:
            fingerprint: 指纹标识符字符串
        """
        self.config["fingerprint"] = fingerprint
        if self._initialized:
            raise RuntimeError(
                "HttpFetcher.set_fingerprint must be called before init(); "
                "to switch fingerprint after init, call close() then init() again"
            )
