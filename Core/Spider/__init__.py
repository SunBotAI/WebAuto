"""
Core/Spider — 并发爬虫引擎

支持中途 kill 重启后从 checkpoint 续跑，不重复爬取。
"""
from .spider import Spider
from .task import SpiderTask, TaskStatus

__all__ = [
    "Spider",
    "SpiderTask",
    "TaskStatus",
]
