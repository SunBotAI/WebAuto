"""
隐形模式获取器
基于 Playwright headless + 反检测注入,绕过 90% 反爬
"""
from typing import Optional, Dict, Any, List
from playwright.async_api import (
    async_playwright, Browser, BrowserContext, Page, ElementHandle
)

from .base import BaseFetcher, FetcherMode, FetcherResponse
from Core.AntiDetect import AntiDetectInjector, AntiDetectConfig
try:
    from Core.BrowserProfile import ProfileStore
    _HAS_PROFILE = True
except Exception:
    _HAS_PROFILE = False
from Core.Errors import (
    FetcherInitError,
    FetcherNetworkError,
    ElementNotFoundError,
)


class StealthFetcher(BaseFetcher):
    """隐形模式获取器,绕过 90% 反爬"""
    
    mode = FetcherMode.STEALTH
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._anti_detect: Optional[AntiDetectInjector] = None
        
    async def init(self) -> None:
        """初始化 Playwright + 反检测注入"""
        try:
            self._playwright = await async_playwright().start()
            
            # 浏览器配置
            headless = self.config.get('headless', True)
            browser_type = self.config.get('browser_type', 'chromium')
            
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ]
            
            if browser_type == "chromium":
                self._browser = await self._playwright.chromium.launch(
                    headless=headless,
                    args=launch_args,
                )
            elif browser_type == "firefox":
                self._browser = await self._playwright.firefox.launch(
                    headless=headless,
                )
            else:
                raise FetcherInitError(f"Unsupported browser type: {browser_type}")
                
            # === 加载 BrowserProfile (可选) ===
            profile = None
            if _HAS_PROFILE:
                pid = self.config.get("browser_profile_id")
                if pid:
                    store = ProfileStore()
                    profile = store.get_or_create(
                        pid,
                        seed=self.config.get("browser_profile_seed"),
                        label=self.config.get("browser_profile_label", pid),
                    )
                    print(f"[StealthFetcher] using BrowserProfile: {profile.profile_id} seed={profile.fingerprint_seed}")

            # === 创建上下文:优先用 profile 值,否则用 config 兜底 ===
            viewport = self.config.get('viewport', {"width": 1920, "height": 1080})
            user_agent = self.config.get(
                'user_agent',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
            locale     = self.config.get('locale', "zh-CN")
            timezone   = self.config.get('timezone_id', "Asia/Shanghai")
            color_schm = self.config.get('color_scheme', "light")
            if profile is not None:
                pw_kw = profile.apply_to_playwright_kwargs()
                viewport = pw_kw["viewport"]
                user_agent = pw_kw["user_agent"]
                locale = pw_kw["locale"]
                timezone = pw_kw["timezone_id"]
                color_schm = pw_kw["color_scheme"]

            self._context = await self._browser.new_context(
                viewport=viewport,
                user_agent=user_agent,
                locale=locale,
                timezone_id=timezone,
                color_scheme=color_schm,
                accept_downloads=True,
            )

            # === 注入反检测(必须在创建页面前注入到 context) ===
            if self.config.get('anti_detect', True):
                ad_cfg = AntiDetectConfig(**self.config.get('anti_detect_config', {}))
                if profile is not None:
                    profile.apply_to_anti_detect_config(ad_cfg)
                self._anti_detect = AntiDetectInjector(ad_cfg)
                await self._anti_detect.inject(self._context)
                
            # 创建页面
            self._page = await self._context.new_page()
            
            self._initialized = True
            print("[StealthFetcher] Initialized with anti-detect")
            
        except Exception as e:
            raise FetcherInitError(f"StealthFetcher init failed: {e}") from e
            
    async def close(self) -> None:
        """关闭浏览器"""
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
            
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._initialized = False
        print("[StealthFetcher] Closed")
        
    async def get(self, url: str, **kwargs) -> FetcherResponse:
        """GET 请求(页面导航)"""
        if not self._page:
            raise FetcherInitError("StealthFetcher not initialized")
            
        timeout = kwargs.get('timeout', 30000)
        wait_until = kwargs.get('wait_until', 'domcontentloaded')
        
        try:
            response = await self._page.goto(
                url,
                timeout=timeout,
                wait_until=wait_until,
            )
            
            if not response:
                raise FetcherNetworkError(f"No response for {url}")
                
            content = await self._page.content()
            
            return FetcherResponse(
                url=url,
                status=response.status,
                headers=dict(response.headers),
                content=content.encode('utf-8'),
                text=content,
                page=self._page,
            )
            
        except Exception as e:
            raise FetcherNetworkError(f"GET {url} failed: {e}") from e
            
    async def post(self, url: str, data: Any = None, json: Any = None, **kwargs) -> FetcherResponse:
        """
        POST 请求(通过页面 evaluate 执行 fetch)

        Notes:
            这是浏览器内的 fetch,会受 fetch hook / CORS / SameSite 等影响,
            因此更适合同源业务 API。跨域 POST 请用 HttpFetcher。
        """
        if not self._page:
            raise FetcherInitError("StealthFetcher not initialized")

        # 把 Python 数据转成能在 JS fetch() 里直接使用的字面量
        if json is not None:
            body_kind = "json"
            body_payload = json
        elif data is not None:
            body_kind = "form"
            if isinstance(data, (bytes, bytearray)):
                # 二进制 body: 走 base64,JS 侧再 decode
                import base64
                body_kind = "binary"
                body_payload = base64.b64encode(bytes(data)).decode("ascii")
            else:
                body_payload = data
        else:
            body_kind = "none"
            body_payload = None

        # buildBody 根据 kind 在 JS 侧生成 fetch init,避免 Python repr 不可移植
        script = """
        async ([url, kind, payload, headers]) => {
            const init = { method: 'POST', credentials: 'include', headers: { ...headers } };
            if (kind === 'json') {
                init.body = JSON.stringify(payload);
                init.headers['Content-Type'] = 'application/json';
            } else if (kind === 'form') {
                init.body = new URLSearchParams(payload).toString();
                init.headers['Content-Type'] = 'application/x-www-form-urlencoded';
            } else if (kind === 'binary') {
                const bin = atob(payload);
                const arr = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
                init.body = arr;
            }
            const res = await fetch(url, init);
            return {
                status: res.status,
                headers: Object.fromEntries(res.headers.entries()),
                text: await res.text(),
            };
        }
        """

        try:
            result = await self._page.evaluate(
                script, [url, body_kind, body_payload, kwargs.get('headers', {})]
            )
        except Exception as e:
            raise FetcherNetworkError(f"POST {url} failed: {e}") from e

        return FetcherResponse(
            url=url,
            status=result['status'],
            headers=result['headers'],
            content=result['text'].encode('utf-8'),
            text=result['text'],
            page=self._page,
        )
        
    async def find(self, selector: str, **kwargs) -> Optional[ElementHandle]:
        """查找元素"""
        if not self._page:
            raise ElementNotFoundError("No page loaded")
            
        timeout = kwargs.get('timeout', 5000)
        
        try:
            element = await self._page.wait_for_selector(selector, timeout=timeout)
            return element
        except:
            return None
            
    async def find_all(self, selector: str, **kwargs) -> List[ElementHandle]:
        """查找所有匹配元素"""
        if not self._page:
            return []
            
        return await self._page.query_selector_all(selector)
        
    async def extract(self, selector: str, attribute: Optional[str] = None) -> Optional[str]:
        """提取文本或属性"""
        element = await self.find(selector)
        if element is None:
            return None
            
        if attribute:
            return await element.get_attribute(attribute)
        return await element.inner_text()
        
    async def click(self, selector: str, **kwargs) -> None:
        """点击元素"""
        element = await self.find(selector)
        if element is None:
            raise ElementNotFoundError(f"Element not found for click: {selector}")
            
        await element.click(**kwargs)
        
    async def type(self, selector: str, text: str, **kwargs) -> None:
        """输入文本"""
        element = await self.find(selector)
        if element is None:
            raise ElementNotFoundError(f"Element not found for type: {selector}")
            
        delay = kwargs.get('delay', 50)  # 默认 50ms 输入间隔,模拟人类
        await element.type(text, delay=delay)
        
    async def screenshot(self, path: Optional[str] = None, **kwargs) -> bytes:
        """截图"""
        if not self._page:
            raise FetcherInitError("StealthFetcher not initialized")
            
        return await self._page.screenshot(path=path, **kwargs)
        
    async def evaluate(self, script: str, *args) -> Any:
        """执行 JS"""
        if not self._page:
            raise FetcherInitError("StealthFetcher not initialized")
            
        return await self._page.evaluate(script, *args)
        
    async def wait_for(self, selector: str, **kwargs) -> None:
        """等待元素出现"""
        if not self._page:
            raise FetcherInitError("StealthFetcher not initialized")
            
        timeout = kwargs.get('timeout', 30000)
        await self._page.wait_for_selector(selector, timeout=timeout)
        
    # ===== 会话管理 =====
    
    def get_cookies(self) -> Dict[str, str]:
        """获取当前 Cookies"""
        if not self._context:
            return {}
            
        cookies = {}
        for c in self._context.cookies():
            cookies[c['name']] = c['value']
        return cookies
        
    def set_cookies(self, cookies: Dict[str, str]) -> None:
        """设置 Cookies"""
        if not self._context:
            return
            
        cookie_list = []
        for k, v in cookies.items():
            cookie_list.append({'name': k, 'value': v})
        self._context.add_cookies(cookie_list)
        
    def set_proxy(self, proxy: Optional[str]) -> None:
        """设置代理(需要重启浏览器生效)"""
        if self._initialized:
            print("[StealthFetcher] Warning: proxy will take effect on next init")
        self.config['proxy'] = proxy
        
    @property
    def page(self) -> Optional[Page]:
        """获取原始 Page 对象(向后兼容)"""
        return self._page
        
    @property
    def context(self) -> Optional[BrowserContext]:
        return self._context
