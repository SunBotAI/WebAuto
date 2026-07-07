"""
纯 HTTP 获取器
使用 httpx,支持 HTTP/3、TLS 指纹模拟,速度最快
"""
from typing import Optional, Dict, Any, List
import httpx
from lxml import html

from .base import BaseFetcher, FetcherMode, FetcherResponse


# ===== 浏览器伪装:Chrome 120 的标准 header 顺序 =====
# httpx 用 dict 插入顺序写 header,所以按 Chrome 实际发送顺序装填 key。
# 真实 Chrome 120 在 GET 文档时的 header 顺序(常见 Profile):
_CHROME_HEADER_ORDER = [
    "Host",                          # httpx 会自动加
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
    """把 headers dict 转成 **有序** 的 list of (k, v) 元组。

    顺序: 按 _CHROME_HEADER_ORDER 出现顺序排,其他未知的 header 放最后(保持相对顺序)。
    httpx 0.25+ 支持 headers=[(k,v), ...] 这种 list 形式,会按 list 顺序发出。
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
    """纯 HTTP 模式获取器,速度最快"""
    
    mode = FetcherMode.HTTP
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._client: Optional[httpx.AsyncClient] = None
        self._cookies: Dict[str, str] = {}
        self._proxy: Optional[str] = None
        self._last_response: Optional[FetcherResponse] = None
        self._last_dom: Optional[html.HtmlElement] = None
        
    async def init(self) -> None:
        """初始化 HTTP 客户端"""
        try:
            # 默认配置
            timeout = self.config.get('timeout', 30)
            follow_redirects = self.config.get('follow_redirects', True)
            http2 = self.config.get('http2', True)
            http3 = self.config.get('http3', False)
            
            # 模拟浏览器指纹。dict 插入顺序通过 _normalize_headers 转 Chrome header order。
            # 优先级: BrowserProfile.apply_to_http_headers() > config.headers > 兜底。
            from Core.AntiDetect import AntiDetectConfig as _AD  # 仅取依赖顺序

            headers_dict = {
                'sec-ch-ua':          '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile':   '?0',
                'sec-ch-ua-platform': '"macOS"',
                'Upgrade-Insecure-Requests': '1',
                'User-Agent': self.config.get(
                    'user_agent',
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
            }
            # 接 profile / config.headers(允许覆盖默认值)
            extra = self.config.get('headers') or {}
            headers_dict.update({k: v for k, v in extra.items() if v is not None})

            # 接 BrowserProfile(如果传了 browser_profile_id)
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

            headers_ordered = _normalize_headers(headers_dict)
            
            transport = None
            if http3:
                try:
                    from httpx import HTTPTransport
                    # httpx[http3] 需要单独安装
                except ImportError:
                    pass
            
                        # httpx 0.28+ 改用 proxy(单数),兼容老版本先尝试新参数
            client_kwargs = dict(
                timeout=timeout,
                follow_redirects=follow_redirects,
                http2=http2,
                headers=headers_ordered,
                cookies=self._cookies,
            )
            try:
                if self._proxy:
                    self._client = httpx.AsyncClient(proxy=self._proxy, **client_kwargs)
                else:
                    self._client = httpx.AsyncClient(**client_kwargs)
            except TypeError:
                # 老版本 httpx: proxies(复数)
                client_kwargs['proxies'] = self._proxy or None
                self._client = httpx.AsyncClient(**client_kwargs)
            
            self._initialized = True
            print("[HttpFetcher] Initialized")
            
        except Exception as e:
            raise FetcherInitError(f"HttpFetcher init failed: {e}") from e
            
    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._initialized = False
        print("[HttpFetcher] Closed")
        
    async def get(self, url: str, **kwargs) -> FetcherResponse:
        """GET 请求"""
        if not self._client:
            raise FetcherInitError("HttpFetcher not initialized")
            
        try:
            response = await self._client.get(url, **kwargs)
            return self._build_response(response)
        except httpx.TimeoutException as e:
            raise FetcherTimeoutError(f"GET {url} timeout: {e}") from e
        except httpx.NetworkError as e:
            raise FetcherNetworkError(f"GET {url} network error: {e}") from e
        except Exception as e:
            raise FetcherNetworkError(f"GET {url} failed: {e}") from e
            
    async def post(self, url: str, data: Any = None, json: Any = None, **kwargs) -> FetcherResponse:
        """POST 请求"""
        if not self._client:
            raise FetcherInitError("HttpFetcher not initialized")
            
        try:
            response = await self._client.post(url, data=data, json=json, **kwargs)
            return self._build_response(response)
        except httpx.TimeoutException as e:
            raise FetcherTimeoutError(f"POST {url} timeout: {e}") from e
        except httpx.NetworkError as e:
            raise FetcherNetworkError(f"POST {url} network error: {e}") from e
        except Exception as e:
            raise FetcherNetworkError(f"POST {url} failed: {e}") from e
            
    def _build_response(self, response: httpx.Response) -> FetcherResponse:
        """构建统一响应对象"""
        # 解析 DOM
        try:
            dom = html.fromstring(response.text)
        except:
            dom = None
            
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
        # lxml 6.x 中空 HtmlElement __bool__ 会触发 FutureWarning 且可能误判,
        # 统一用 len 判断(根节点 >=1 子节点才算"加载过")
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
        
    async def extract(self, selector: str, attribute: Optional[str] = None) -> Optional[str]:
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
        # HTTP 模式下直接检查元素是否存在
        element = await self.find(selector)
        if element is None:
            raise ElementNotFoundError(f"Element not found: {selector}")
            
    # ===== 会话管理 =====
    
    def get_cookies(self) -> Dict[str, str]:
        """获取当前 Cookies"""
        if self._client:
            return dict(self._client.cookies)
        return self._cookies.copy()
        
    def set_cookies(self, cookies: Dict[str, str]) -> None:
        """设置 Cookies"""
        self._cookies.update(cookies)
        if self._client:
            for k, v in cookies.items():
                self._client.cookies.set(k, v)
                
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
