"""
Spider task 数据类
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SpiderTask:
    """Spider 任务单元"""
    url: str
    task_id: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    # 爬取结果（由 subclass process() 填充）
    result: Optional[Dict[str, Any]] = None
    # 错误信息
    error: Optional[str] = None
    # 重试次数
    retry: int = 0
    # HTTP 状态码
    status_code: Optional[int] = None
    # 已爬时间戳
    crawled_at: Optional[str] = None

    def __post_init__(self):
        if self.task_id is None:
            self.task_id = self.url
