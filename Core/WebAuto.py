"""
WebAuto 主入口模块
整合所有核心能力,提供统一的自动化接口

与 ShopAuto 架构风格一致,PascalCase 命名
"""
import asyncio
from typing import Optional
from dataclasses import dataclass

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from .CaptchaSolver import CaptchaSolver
from .AntiDetect import AntiDetectInjector, AntiDetectConfig, inject_anti_detect
from .TimeSync import TimeSync, create_timesync


@dataclass
class WebAutoConfig:
    """WebAuto 全局配置"""
    headless: bool = False
    anti_detect: bool = True
    enable_captcha_solver: bool = True
    enable_time_sync: bool = True
    browser_type: str = "chromium"  # chromium / firefox / webkit


class WebAuto:
    """
    Web 页面自动化主类
    整合反检测、验证码识别、高精度时间同步等能力
    """
    
    def __init__(self, config: Optional[WebAutoConfig] = None):
        self.config = config or WebAutoConfig()
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        
        # 子模块
        self._captcha_solver: Optional[CaptchaSolver] = None
        self._time_sync: Optional[TimeSync] = None
        self._anti_detect: Optional[AntiDetectInjector] = None
        
    async def init(self) -> None:
        """初始化浏览器和所有模块"""
        self._playwright = await async_playwright().start()
        
        # 启动浏览器
        if self.config.browser_type == "chromium":
            self._browser = await self._playwright.chromium.launch(
                headless=self.config.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]
            )
        elif self.config.browser_type == "firefox":
            self._browser = await self._playwright.firefox.launch(
                headless=self.config.headless
            )
        elif self.config.browser_type == "webkit":
            self._browser = await self._playwright.webkit.launch(
                headless=self.config.headless
            )
        else:
            raise ValueError(f"Unknown browser type: {self.config.browser_type}")
            
        # 创建上下文
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        
        # 创建页面
        self._page = await self._context.new_page()
        
        # 注入反检测
        if self.config.anti_detect:
            self._anti_detect = AntiDetectInjector()
            await self._anti_detect.inject(self._page)
            
        # 初始化验证码识别
        if self.config.enable_captcha_solver:
            self._captcha_solver = CaptchaSolver()
            # 延迟初始化,第一次使用时真正加载 OCR 引擎
            
        # 初始化时间同步
        if self.config.enable_time_sync:
            try:
                self._time_sync = await create_timesync()
            except Exception as e:
                # NTP 在沙箱/局域网/防火墙环境下可能完全不可达
                # 降级为无 time-sync 模式,业务可通过 auto.time 抛错感知
                print(f"[WebAuto] Time sync failed: {e}, continuing without sync")
                self._time_sync = None
            
        print("[WebAuto] Initialized")
        if self._time_sync and self._time_sync.calibrated:
            print(
                f"[WebAuto] Time synced: offset {self._time_sync.stats.offset_ms:+.1f}ms, "
                f"jitter {self._time_sync.stats.jitter_ms:.1f}ms"
            )
            
    async def goto(self, url: str, **kwargs) -> None:
        """导航到指定 URL"""
        if not self._page:
            raise RuntimeError("WebAuto not initialized, call init() first")
        await self._page.goto(url, **kwargs)
        
    @property
    def page(self) -> Page:
        """获取 Playwright Page 对象"""
        if not self._page:
            raise RuntimeError("WebAuto not initialized, call init() first")
        return self._page
        
    @property
    def browser(self) -> Browser:
        """获取 Browser 对象"""
        if not self._browser:
            raise RuntimeError("WebAuto not initialized, call init() first")
        return self._browser
        
    @property
    def context(self) -> BrowserContext:
        """获取 BrowserContext 对象"""
        if not self._context:
            raise RuntimeError("WebAuto not initialized, call init() first")
        return self._context
        
    @property
    def captcha(self) -> CaptchaSolver:
        """验证码求解器"""
        if not self._captcha_solver:
            raise RuntimeError("Captcha solver disabled in config")
        return self._captcha_solver
        
    @property
    def time(self) -> TimeSync:
        """时间同步器"""
        if not self._time_sync:
            raise RuntimeError("Time sync disabled in config")
        return self._time_sync
        
    async def close(self) -> None:
        """关闭浏览器和清理资源"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        print("[WebAuto] Closed")
        
    async def __aenter__(self):
        await self.init()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
