"""
获取器模块
四种模式:http / stealth / browser / human
"""
from .base import BaseFetcher, FetcherMode, FetcherResponse
from .http import HttpFetcher
from .stealth import StealthFetcher
from .browser import BrowserFetcher
from .human import HumanFetcher


def create_fetcher(mode: str = 'browser', config: dict = None) -> BaseFetcher:
    """
    工厂函数:创建获取器
    
    Args:
        mode: 'http' | 'stealth' | 'browser' | 'human'
        config: 配置字典
    """
    mode_enum = FetcherMode(mode)
    config = config or {}
    
    fetcher_map = {
        FetcherMode.HTTP: HttpFetcher,
        FetcherMode.STEALTH: StealthFetcher,
        FetcherMode.BROWSER: BrowserFetcher,
        FetcherMode.HUMAN: HumanFetcher,
    }
    
    fetcher_class = fetcher_map.get(mode_enum)
    if not fetcher_class:
        raise ValueError(f"Unknown fetcher mode: {mode}")
        
    return fetcher_class(config)


__all__ = [
    'BaseFetcher',
    'FetcherMode',
    'FetcherResponse',
    'HttpFetcher',
    'StealthFetcher',
    'BrowserFetcher',
    'HumanFetcher',
    'create_fetcher',
]
