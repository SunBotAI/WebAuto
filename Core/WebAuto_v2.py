"""
WebAuto v2.0 主入口
整合获取器抽象层 + 智能选择器 + 原有核心能力

向后兼容:原有 API 全部保留,可无缝迁移
"""
import asyncio
from typing import Optional, Dict, Any, Union, List
from dataclasses import dataclass, field

from .CaptchaSolver import CaptchaSolver
from .AntiDetect import AntiDetectInjector, AntiDetectConfig
from .TimeSync import TimeSync, create_timesync
from .Fetchers import (
    BaseFetcher,
    create_fetcher,
    FetcherMode,
)
from .Selector import SelectorFactory, SmartSelector
from .Errors import WebAutoError


@dataclass
class WebAutoConfig:
    """
    WebAuto 全局配置
    
    向后兼容:v1.0 的配置项全部保留
    """
    # v1.0 兼容配置
    headless: bool = False
    anti_detect: bool = True
    enable_captcha_solver: bool = True
    enable_time_sync: bool = True
    browser_type: str = "chromium"
    
    # v2.0 新增配置
    mode: str = "browser"  # http / stealth / browser / human
    timeout: int = 30000
    retry: int = 3
    
    # 获取器配置
    fetcher_config: Dict[str, Any] = field(default_factory=dict)
    
    # 智能选择器默认配置
    selector_timeout: int = 5000
    selector_retry: int = 3


class WebAuto:
    """
    Web 自动化主类 v2.0
    
    新特性:
    - 四种运行模式:http / stealth / browser / human
    - 智能选择器:重试 + 超时 + fallback + 自适应
    - 统一 API:所有模式下调用方式完全一致
    
    向后兼容:
    - async with WebAuto(config) as auto: 不变
    - auto.page / auto.browser / auto.context 不变
    - auto.captcha / auto.time 不变
    """
    
    def __init__(self, config: Optional[WebAutoConfig] = None):
        self.config = config or WebAutoConfig()
        self._fetcher: Optional[BaseFetcher] = None
        self._selector_factory: Optional[SelectorFactory] = None
        
        # v1.0 兼容模块
        self._captcha_solver: Optional[CaptchaSolver] = None
        self._time_sync: Optional[TimeSync] = None
        
        # 运行状态
        self._initialized = False
        
    async def init(self) -> None:
        """初始化 WebAuto"""
        if self._initialized:
            return
            
        # 构建获取器配置(向后兼容 v1.0)
        fetcher_config = self.config.fetcher_config.copy()
        fetcher_config.setdefault('headless', self.config.headless)
        fetcher_config.setdefault('browser_type', self.config.browser_type)
        fetcher_config.setdefault('anti_detect', self.config.anti_detect)
        fetcher_config.setdefault('timeout', self.config.timeout)
        
        # 创建获取器
        self._fetcher = create_fetcher(self.config.mode, fetcher_config)
        await self._fetcher.init()
        
        # 创建选择器工厂
        self._selector_factory = SelectorFactory(self._fetcher)
        
        # 初始化验证码识别
        if self.config.enable_captcha_solver:
            self._captcha_solver = CaptchaSolver()
            # 延迟加载 OCR 引擎,第一次使用时真正初始化
            
        # 初始化时间同步
        if self.config.enable_time_sync:
            try:
                self._time_sync = await create_timesync()
            except Exception as e:
                print(f"[WebAuto] Time sync failed: {e}, continuing without sync")
                
        self._initialized = True
        print(f"[WebAuto] Initialized in {self.config.mode} mode")
        
        if self._time_sync and self._time_sync.calibrated:
            print(
                f"[WebAuto] Time synced: offset {self._time_sync.stats.offset_ms:+.1f}ms, "
                f"jitter {self._time_sync.stats.jitter_ms:.1f}ms"
            )
            
    async def close(self) -> None:
        """关闭并清理资源"""
        if self._fetcher:
            await self._fetcher.close()
            
        self._initialized = False
        print("[WebAuto] Closed")
        
    # ===== 核心操作 API =====
    
    async def goto(self, url: str, **kwargs) -> Any:
        """导航到指定 URL"""
        if not self._fetcher:
            raise WebAutoError("WebAuto not initialized")
        return await self._fetcher.get(url, **kwargs)
        
    def find(
        self,
        selector: Union[str, List[str]],
        **kwargs,
    ) -> SmartSelector:
        """
        智能选择器,链式调用
        
        用法:
            await auto.find('.submit-btn').retry(3).timeout(5000).click()
            await auto.find(['.btn', '#submit']).click()
        """
        if not self._selector_factory:
            raise WebAutoError("WebAuto not initialized")
            
        # 合并默认配置
        kwargs.setdefault('timeout', self.config.selector_timeout)
        kwargs.setdefault('retry', self.config.selector_retry)
        
        return self._selector_factory(selector, **kwargs)
        
    def find_by_text(self, text: str, tag: str = '*') -> SmartSelector:
        """
        按文本查找元素,不用写 CSS 选择器
        
        用法:
            await auto.find_by_text('立即购买').click()
        """
        if not self._selector_factory:
            raise WebAutoError("WebAuto not initialized")
        return self._selector_factory.by_text(text, tag)
        
    async def extract(self, selector: str, attribute: Optional[str] = None) -> Optional[str]:
        """提取文本或属性"""
        if not self._fetcher:
            raise WebAutoError("WebAuto not initialized")
        return await self._fetcher.extract(selector, attribute)
        
    async def screenshot(self, path: Optional[str] = None, **kwargs) -> bytes:
        """截图"""
        if not self._fetcher:
            raise WebAutoError("WebAuto not initialized")
        return await self._fetcher.screenshot(path=path, **kwargs)
        
    async def evaluate(self, script: str, *args) -> Any:
        """执行 JS"""
        if not self._fetcher:
            raise WebAutoError("WebAuto not initialized")
        return await self._fetcher.evaluate(script, *args)
        
    async def solve_captcha(
        self,
        page=None,
        auto_click: bool = True,
        **kwargs,
    ) -> Any:
        """
        自动识别并点击验证码

        Args:
            page: 可选,显式传入 Playwright Page。不传则用 fetcher 自带的 page。
            auto_click: 识别成功后是否在页面上自动点击。
            **kwargs: 透传给 CaptchaSolver.solve_from_page。

        Returns:
            CaptchaResult,带有 success / points / target_text 等字段。

        典型用法:
            result = await auto.solve_captcha()
            if result.success:
                print("已识别并点击:", result.points)
        """
        if not self._captcha_solver:
            raise WebAutoError("Captcha solver not enabled")

        # 解析 page: 显式传入 > fetcher.page > 报错
        target_page = page
        if target_page is None:
            try:
                target_page = self._fetcher.page  # type: ignore[attr-defined]
            except AttributeError:
                raise WebAutoError(
                    "Current fetcher does not expose .page; "
                    "solve_captcha requires a browser-based mode or explicit page= argument"
                )

        result = await self._captcha_solver.solve_from_page(target_page, **kwargs)
        if auto_click and result.success and result.points:
            await self._captcha_solver.click_points(target_page, result)
        return result
        
    # ===== 会话管理 =====
    
    @property
    def cookies(self) -> Dict[str, str]:
        """获取 Cookies"""
        if not self._fetcher:
            return {}
        return self._fetcher.get_cookies()
        
    def set_cookies(self, cookies: Dict[str, str]) -> None:
        """设置 Cookies"""
        if self._fetcher:
            self._fetcher.set_cookies(cookies)
            
    def set_proxy(self, proxy: Optional[str]) -> None:
        """设置代理"""
        if self._fetcher:
            self._fetcher.set_proxy(proxy)
            
    # ===== v1.0 向后兼容属性 =====
    
    @property
    def page(self) -> Any:
        """获取 Playwright Page 对象(仅 browser/stealth/human 模式)"""
        if hasattr(self._fetcher, 'page'):
            return self._fetcher.page
        raise WebAutoError(f"Current mode {self.config.mode} does not have page")
        
    @property
    def browser(self) -> Any:
        """获取 Browser 对象(向后兼容)"""
        if hasattr(self._fetcher, '_browser'):
            return self._fetcher._browser
        raise WebAutoError(f"Current mode {self.config.mode} does not have browser")
        
    @property
    def context(self) -> Any:
        """获取 BrowserContext 对象(向后兼容)"""
        if hasattr(self._fetcher, 'context'):
            return self._fetcher.context
        raise WebAutoError(f"Current mode {self.config.mode} does not have context")
        
    @property
    def captcha(self) -> CaptchaSolver:
        """验证码求解器(向后兼容)"""
        if not self._captcha_solver:
            raise WebAutoError("Captcha solver not enabled")
        return self._captcha_solver
        
    @property
    def time(self) -> TimeSync:
        """时间同步器(向后兼容)"""
        if not self._time_sync:
            raise WebAutoError("Time sync not enabled")
        return self._time_sync
        
    @property
    def fetcher(self) -> BaseFetcher:
        """获取当前获取器"""
        return self._fetcher
        
    # ===== 上下文管理器 =====
    
    async def __aenter__(self):
        await self.init()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# ===== 便捷工厂函数 =====


def WebAutoHttp(**kwargs) -> WebAuto:
    """快速创建 HTTP 模式实例"""
    config = WebAutoConfig(mode='http', **kwargs)
    return WebAuto(config)


def WebAutoStealth(**kwargs) -> WebAuto:
    """快速创建隐形模式实例"""
    config = WebAutoConfig(mode='stealth', **kwargs)
    return WebAuto(config)


def WebAutoBrowser(**kwargs) -> WebAuto:
    """快速创建浏览器模式实例"""
    config = WebAutoConfig(mode='browser', **kwargs)
    return WebAuto(config)


def WebAutoHuman(**kwargs) -> WebAuto:
    """快速创建人类模式实例(抢购专用)"""
    config = WebAutoConfig(mode='human', **kwargs)
    return WebAuto(config)
