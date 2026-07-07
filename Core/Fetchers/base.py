"""
获取器抽象基类
定义所有 Fetcher 必须实现的统一接口
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass
from enum import Enum


class FetcherMode(Enum):
    """获取器模式枚举"""
    HTTP = 'http'        # 纯 HTTP 模式,最快
    STEALTH = 'stealth'  # 隐形模式,绕过 90% 反爬
    BROWSER = 'browser'  # 完整浏览器,交互场景
    HUMAN = 'human'      # 人类模式,抢购专用


@dataclass
class FetcherResponse:
    """统一响应对象"""
    url: str
    status: int
    headers: Dict[str, str]
    content: bytes
    text: str
    # 可选:解析后的 DOM 对象
    dom: Optional[Any] = None
    # 可选:Playwright Page 对象(仅浏览器模式)
    page: Optional[Any] = None
    
    def __str__(self) -> str:
        return f"<FetcherResponse {self.status} {self.url[:80]}>"


class BaseFetcher(ABC):
    """
    获取器抽象基类
    
    所有 Fetcher 必须实现这些接口,保证上层调用方式统一
    """
    
    mode: FetcherMode
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._initialized = False
        
    @abstractmethod
    async def init(self) -> None:
        """初始化获取器"""
        pass
        
    @abstractmethod
    async def close(self) -> None:
        """关闭获取器,清理资源"""
        pass
        
    @abstractmethod
    async def get(self, url: str, **kwargs) -> FetcherResponse:
        """GET 请求"""
        pass
        
    @abstractmethod
    async def post(self, url: str, data: Any = None, json: Any = None, **kwargs) -> FetcherResponse:
        """POST 请求"""
        pass
        
    @abstractmethod
    async def find(self, selector: str, **kwargs) -> Any:
        """查找元素"""
        pass
        
    @abstractmethod
    async def find_all(self, selector: str, **kwargs) -> List[Any]:
        """查找所有匹配元素"""
        pass
        
    @abstractmethod
    async def extract(self, selector: str, attribute: Optional[str] = None) -> Optional[str]:
        """提取文本或属性"""
        pass
        
    @abstractmethod
    async def click(self, selector: str, **kwargs) -> None:
        """点击元素"""
        pass
        
    @abstractmethod
    async def type(self, selector: str, text: str, **kwargs) -> None:
        """输入文本"""
        pass
        
    @abstractmethod
    async def screenshot(self, path: Optional[str] = None, **kwargs) -> bytes:
        """截图"""
        pass
        
    @abstractmethod
    async def evaluate(self, script: str, *args) -> Any:
        """执行 JS"""
        pass
        
    @abstractmethod
    async def wait_for(self, selector: str, **kwargs) -> None:
        """等待元素出现"""
        pass
        
    # ===== 会话管理 =====
    
    @abstractmethod
    def get_cookies(self) -> Dict[str, str]:
        """获取当前 Cookies"""
        pass
        
    @abstractmethod
    def set_cookies(self, cookies: Dict[str, str]) -> None:
        """设置 Cookies"""
        pass
        
    @abstractmethod
    def set_proxy(self, proxy: Optional[str]) -> None:
        """设置代理"""
        pass
        
    # ===== 上下文管理器 =====
    
    async def __aenter__(self):
        await self.init()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        
    @property
    def initialized(self) -> bool:
        return self._initialized
