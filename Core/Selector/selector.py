"""
智能选择器系统
支持重试、超时、fallback、链式调用
"""
import asyncio
from typing import Optional, List, Any, Union, Callable
from dataclasses import dataclass

from Core.Errors import (
    ElementNotFoundError,
    SelectorTimeoutError,
)


@dataclass
class SelectorConfig:
    """选择器配置"""
    timeout: int = 5000          # 超时时间 ms
    retry: int = 3               # 重试次数
    retry_delay: float = 0.5     # 重试间隔秒
    adaptive: bool = False       # 自适应匹配
    fallback: List[str] = None   # 备用选择器列表


class SmartSelector:
    """
    智能选择器,链式调用 API
    
    用法:
        btn = await auto.find('.submit-btn')
                         .retry(3)
                         .timeout(5000)
                         .adaptive(True)
                         .fallback(['#submit', '[type=submit]'])
                         .get()
    """
    
    def __init__(
        self,
        selector: Union[str, List[str]],
        fetcher: Any,
        config: Optional[SelectorConfig] = None,
    ):
        self._selector = selector
        self._fetcher = fetcher
        self._config = config or SelectorConfig()
        self._by_text: Optional[str] = None
        self._element: Optional[Any] = None
        
    def retry(self, times: int) -> 'SmartSelector':
        """设置重试次数"""
        self._config.retry = times
        return self
        
    def timeout(self, ms: int) -> 'SmartSelector':
        """设置超时时间"""
        self._config.timeout = ms
        return self
        
    def adaptive(self, enabled: bool = True) -> 'SmartSelector':
        """启用自适应匹配"""
        self._config.adaptive = enabled
        return self
        
    def fallback(self, selectors: List[str]) -> 'SmartSelector':
        """设置备用选择器"""
        self._config.fallback = selectors
        return self
        
    def by_text(self, text: str) -> 'SmartSelector':
        """按文本查找"""
        self._by_text = text
        return self
        
    async def get(self) -> Optional[Any]:
        """获取元素"""
        selectors = self._get_all_selectors()

        for attempt in range(self._config.retry):
            for selector in selectors:
                try:
                    element = await self._try_find(selector)
                    if element is not None:
                        self._element = element
                        return element
                except Exception as e:
                    if attempt == self._config.retry - 1:
                        print(f"[SmartSelector] Attempt {attempt + 1} failed: {e}")

            # 重试延迟
            if attempt < self._config.retry - 1:
                await asyncio.sleep(self._config.retry_delay)

        # 全部失败:用 adaptive 文本回退
        if self._config.adaptive:
            element = await self._adaptive_text_match()
            if element is not None:
                self._element = element
                return element

        raise ElementNotFoundError(
            f"Element not found after {self._config.retry} attempts: {selectors}"
        )

    async def _adaptive_text_match(self) -> Optional[Any]:
        """自适应匹配:用主选择器抽取的 tag 名,遍历全页同 tag 找含目标文本的节点

        适用场景:选择器写错(类名改了、id 变了),但目标节点的 tag/语义文字没变。
        触发条件:必须在 get() 之前调用 .by_text(...) 给出目标文字,否则降级失败。
        """
        if not self._by_text:
            return None
        # 拿主选择器的 tag 名字
        primary = self._selector[0] if isinstance(self._selector, list) else self._selector
        tag = "button"  # 默认兜底
        if isinstance(primary, str):
            stripped = primary.strip()
            if stripped.startswith((".", "#", "[")):
                tag = "button"  # class/id/attr 选择器,默认扫 button
            elif stripped and stripped[0].isalpha():
                # tag 选择器: '.btn > a' 取首段
                tag = stripped.split()[0].split(">")[0].split(".")[0] or "button"
        try:
            return await self._find_by_text(tag, self._by_text)
        except Exception:
            return None
        
    def _get_all_selectors(self) -> List[str]:
        """获取所有待尝试的选择器"""
        selectors = []
        
        if isinstance(self._selector, str):
            selectors.append(self._selector)
        elif isinstance(self._selector, list):
            selectors.extend(self._selector)
            
        if self._config.fallback:
            selectors.extend(self._config.fallback)
            
        return selectors if selectors else ['*']
        
    async def _try_find(self, selector: str) -> Optional[Any]:
        """尝试查找单个选择器"""
        if self._by_text:
            # 按文本查找
            return await self._find_by_text(selector, self._by_text)
            
        return await self._fetcher.find(selector, timeout=self._config.timeout)
        
    async def _find_by_text(self, selector: str, text: str) -> Optional[Any]:
        """按文本查找元素"""
        elements = await self._fetcher.find_all(selector)
        for el in elements:
            try:
                # 不同 fetcher 获取文本方式不同
                if hasattr(el, 'inner_text'):
                    # Playwright ElementHandle
                    el_text = await el.inner_text()
                elif hasattr(el, 'text_content'):
                    # lxml HtmlElement
                    el_text = el.text_content()
                else:
                    continue
                    
                if text in el_text:
                    return el
            except:
                continue
        return None
        
    # ===== 快捷操作 =====
    
    async def click(self, **kwargs) -> None:
        """获取元素并点击"""
        element = await self.get()
        if hasattr(element, 'click'):
            await element.click(**kwargs)
        else:
            await self._fetcher.click(self._selector, **kwargs)
            
    async def type(self, text: str, **kwargs) -> None:
        """获取元素并输入"""
        element = await self.get()
        if hasattr(element, 'type'):
            await element.type(text, **kwargs)
        else:
            await self._fetcher.type(self._selector, text, **kwargs)
            
    async def text(self) -> Optional[str]:
        """获取元素文本"""
        element = await self.get()
        if hasattr(element, 'inner_text'):
            return await element.inner_text()
        elif hasattr(element, 'text_content'):
            return element.text_content()
        return None
        
    async def attribute(self, name: str) -> Optional[str]:
        """获取元素属性"""
        element = await self.get()
        if hasattr(element, 'get_attribute'):
            return await element.get_attribute(name)
        elif hasattr(element, 'get'):
            return element.get(name)
        return None
        
    async def exists(self) -> bool:
        """检查元素是否存在(不抛异常)"""
        try:
            await self.get()
            return True
        except ElementNotFoundError:
            return False
            
    # ===== 抢购专用 =====
    
    async def preheat(self) -> None:
        """预热元素(仅 HumanFetcher 有效)"""
        if hasattr(self._fetcher, 'preheat_element'):
            await self._fetcher.preheat_element(self._selector)
        else:
            # 其他模式下预先定位元素
            _ = await self.get()


class SelectorFactory:
    """选择器工厂,方便创建"""
    
    def __init__(self, fetcher: Any):
        self._fetcher = fetcher
        
    def __call__(
        self,
        selector: Union[str, List[str]],
        **kwargs,
    ) -> SmartSelector:
        config = SelectorConfig(**kwargs)
        return SmartSelector(selector, self._fetcher, config)
        
    def by_text(self, text: str, tag: str = '*') -> SmartSelector:
        """按文本查找元素"""
        return SmartSelector(tag, self._fetcher).by_text(text)
