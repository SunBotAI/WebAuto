"""
完整浏览器模式获取器
基于 StealthFetcher,但默认显示浏览器窗口,适合交互复杂的场景
"""
from typing import Optional, Dict, Any

from .stealth import StealthFetcher
from .base import FetcherMode


class BrowserFetcher(StealthFetcher):
    """完整浏览器模式,默认显示窗口"""
    
    mode = FetcherMode.BROWSER
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        # 默认显示浏览器窗口
        config.setdefault('headless', False)
        # 默认启用反检测
        config.setdefault('anti_detect', True)
        
        super().__init__(config)
        print("[BrowserFetcher] Initialized in browser mode")
