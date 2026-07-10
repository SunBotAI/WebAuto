"""
Spider 并发爬虫引擎
支持中途 kill -9 重启后从断点续跑（不重复爬取）
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .task import SpiderTask, TaskStatus


class Spider(ABC):
    """
    并发爬虫基类。

    子类实现 `process(task)` 核心爬取逻辑，上层调用 `run()` 启动。

    checkpoint 文件格式 (JSON):
    {
        "spider_id": "...",
        "started_at": "ISO8601",
        "completed_at": null,
        "urls": {
            "https://example.com/1": {
                "status": "done|failed|skipped",
                "result": {...},
                "error": null,
                "crawled_at": "ISO8601",
                "status_code": 200
            }
        },
        "stats": {
            "total": 100,
            "done": 50,
            "failed": 2,
            "pending": 48
        }
    }
    """

    # 并发数（子类可覆盖）
    concurrency: int = 5

    # 每个任务最大重试次数
    max_retries: int = 3

    def __init__(
        self,
        urls: Optional[List[str]] = None,
        checkpoint_path: Optional[str] = None,
        *,
        concurrency: Optional[int] = None,
        max_retries: Optional[int] = None,
    ):
        self._urls_provided = urls
        self._checkpoint_path = (
            Path(checkpoint_path) if checkpoint_path else Path("spider_state.json")
        )
        self.concurrency = concurrency if concurrency is not None else self.concurrency
        self.max_retries = max_retries if max_retries is not None else self.max_retries

        # 运行时状态
        self._tasks: Dict[str, SpiderTask] = {}
        self._done_urls: Set[str] = set()
        self._pending_queue: asyncio.Queue[SpiderTask] = asyncio.Queue()
        # 完成计数器（代替 Queue.task_done，避免 cancel 场景丢计数）
        self._completed_count: int = 0
        self._total_to_process: int = 0
        self._running_urls: Set[str] = set()  # 正在处理中的 URL
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._shutdown: bool = False
        self._worker_exc: Exception | None = None

        self._load_checkpoint()
        self._init_tasks(urls)
        self._spider_id = (
            f"{self.__class__.__name__}-"
            f"{hashlib.md5(str(type(self).__name__).encode()).hexdigest()[:6]}"
        )

    # ─── Checkpoint I/O ─────────────────────────────────────────

    def _checkpoint_data(self) -> Dict[str, Any]:
        urls_data = {}
        for url, task in self._tasks.items():
            urls_data[url] = {
                "status": task.status.value,
                "result": task.result,
                "error": task.error,
                "crawled_at": task.crawled_at,
                "status_code": task.status_code,
                "retry": task.retry,
            }
        total = len(self._tasks)
        done = sum(1 for t in self._tasks.values() if t.status == TaskStatus.DONE)
        failed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED)
        pending = sum(1 for t in self._tasks.values() if t.status in (TaskStatus.PENDING, TaskStatus.FAILED))
        return {
            "spider_id": self._spider_id,
            "started_at": getattr(self, "_started_at", None),
            "completed_at": getattr(self, "_completed_at", None),
            "urls": urls_data,
            "stats": {"total": total, "done": done, "failed": failed, "pending": pending},
        }

    def _save_checkpoint(self) -> None:
        try:
            data = self._checkpoint_data()
            # 合并已有 checkpoint 中已完成的 URL（保留历史成功记录）
            # 注意：不要合并非 DONE 状态，否则会覆盖当前 run 的真实状态
            if self._checkpoint_path.exists():
                try:
                    existing = json.loads(self._checkpoint_path.read_text(encoding="utf-8"))
                    for url, info in existing.get("urls", {}).items():
                        if info.get("status") == "done" and url in data["urls"]:
                            # 之前已完成的 URL：若当前状态不是 DONE，保留历史成功记录
                            if data["urls"][url].get("status") != "done":
                                data["urls"][url] = info
                    # 重新统计 done（合并后）
                    data["stats"]["done"] = sum(
                        1 for u, i in data["urls"].items() if i.get("status") == "done"
                    )
                except Exception:
                    pass
            tmp = self._checkpoint_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.rename(self._checkpoint_path)
        except Exception:
            pass

    def _load_checkpoint(self) -> None:
        if not self._checkpoint_path.exists():
            return
        try:
            data = json.loads(self._checkpoint_path.read_text(encoding="utf-8"))
            for url, info in data.get("urls", {}).items():
                status = info.get("status")
                if status == "done":
                    self._done_urls.add(url)
                elif status == "failed":
                    # FAILED 不加入 _done_urls，重启后应重新处理
                    pass
                elif status == "skipped":
                    self._done_urls.add(url)
        except Exception:
            pass

    # ─── Task 初始化 ────────────────────────────────────────────

    def _init_tasks(self, urls: Optional[List[str]]) -> None:
        source = urls if urls is not None else []
        for url in source:
            # 已恢复的任务保留在 self._tasks（任意状态）
            if url in self._tasks:
                # 如果之前标记为 FAILED（kill 时未来得及重试），当作 PENDING 处理
                if self._tasks[url].status == TaskStatus.FAILED:
                    self._tasks[url].status = TaskStatus.PENDING
                    self._tasks[url].retry = 0  # 重置重试计数
                    self._pending_queue.put_nowait(self._tasks[url])
                continue
            # checkpoint 标记为 done 的 URL
            if url in self._done_urls:
                self._tasks[url] = SpiderTask(url=url, status=TaskStatus.SKIPPED)
            else:
                self._tasks[url] = SpiderTask(url=url)
                self._pending_queue.put_nowait(self._tasks[url])
        self._total_to_process = sum(
            1 for t in self._tasks.values()
            if t.status not in (TaskStatus.DONE, TaskStatus.SKIPPED)
        )

    # ─── 核心钩子（子类实现）───────────────────────────────────

    @abstractmethod
    async def process(self, task: SpiderTask) -> Dict[str, Any]:
        """
        爬取单个任务。子类实现核心爬取逻辑。
        Args:
            task: SpiderTask 对象，task.url 是目标 URL
        Returns:
            爬取结果字典（会被写入 checkpoint）
        """
        raise NotImplementedError

    def load_urls(self) -> List[str]:
        """动态加载 URL（可选实现）。子类覆盖。"""
        return []

    # ─── Worker ────────────────────────────────────────────────

    async def _worker(self, worker_id: int) -> None:
        """
        并发 worker：消费 pending 队列，执行 process()。

        关键保证：
        - 每个 queue.get() 有且仅有一次 task_done()
        - 任务处理完成后放入 done_queue（通知主循环）
        - shutdown_event.set() 后立即退出，不继续处理新任务
        """
        while not self._shutdown_event.is_set():
            task: SpiderTask | None = None
            _needs_task_done = False   # 是否需要调用 task_done()
            _needs_done_put = False     # 是否需要放入 done_queue

            try:
                # 带超时等待新任务，避免 worker 永远阻塞
                task = await asyncio.wait_for(
                    self._pending_queue.get(), timeout=0.5
                )
                _needs_task_done = True

                # 防止同一 URL 被多个 worker 同时处理（并发安全）
                if task.url in self._running_urls:
                    # 已被其他 worker 占有：放回队列，让对方处理
                    self._pending_queue.task_done()
                    _needs_task_done = False
                    continue

                # 标记为处理中（原子地）
                self._running_urls.add(task.url)
                task.status = TaskStatus.RUNNING

                try:
                    result = await asyncio.wait_for(
                        self.process(task), timeout=60.0
                    )
                    task.result = result
                    task.crawled_at = datetime.now(timezone.utc).isoformat()
                    self._done_urls.add(task.url)
                    task.status = TaskStatus.DONE
                    _needs_done_put = True

                except asyncio.TimeoutError:
                    task.error = "process timeout (60s)"
                    task.status = TaskStatus.FAILED
                    _needs_done_put = True

                except asyncio.CancelledError:
                    # 被 cancel（shutdown 或 gather 触发）：恢复 URL 状态
                    self._running_urls.discard(task.url)
                    if task.status == TaskStatus.RUNNING:
                        task.status = TaskStatus.PENDING
                        self._pending_queue.put_nowait(task)
                    # task_done() 已在上方处理（_needs_task_done=True）
                    _needs_done_put = False
                    # checkpoint 已在 finally 中保存
                    break

                except Exception as e:
                    self._running_urls.discard(task.url)
                    task.error = str(e)
                    task.retry += 1
                    if task.retry <= self.max_retries:
                        # 还有重试机会：放回队列重试
                        task.status = TaskStatus.PENDING
                        self._pending_queue.put_nowait(task)
                    else:
                        # 重试耗尽：标记失败
                        task.status = TaskStatus.FAILED
                    _needs_done_put = True
                    if self._worker_exc is None:
                        self._worker_exc = e
                    self._shutdown_event.set()
                    if self._shutdown_event.is_set():
                        break

            except asyncio.TimeoutError:
                # 队列暂时为空（0.5s 无新任务）
                continue

            except asyncio.CancelledError:
                # shutdown 触发的 cancel（不太可能在 get() 之外发生）
                break

            finally:
                # 每个 dequeue 必须有 task_done() 配对
                if _needs_task_done and task is not None:
                    self._pending_queue.task_done()

            # 完成任务并刷 checkpoint
            if _needs_done_put and task is not None:
                self._completed_count += 1
                self._save_checkpoint()

            # 释放运行标记
            if task is not None:
                self._running_urls.discard(task.url)

            # 每处理完一个任务后，检查 shutdown 状态
            if self._shutdown_event.is_set():
                break

    # ─── 主循环 ────────────────────────────────────────────────

    async def run(
        self,
        urls: Optional[List[str]] = None,
        checkpoint_path: Optional[str] = None,
    ) -> Dict[str, SpiderTask]:
        """
        启动 Spider 爬虫。

        支持中途 kill -9：
          - 每完成一个任务自动刷 checkpoint 文件
          - 重启后相同 URL 不会重复爬取

        Args:
            urls: URL 列表（None 则调用 load_urls()）
            checkpoint_path: checkpoint 文件路径

        Returns:
            {url: SpiderTask} 字典
        """
        if checkpoint_path:
            self._checkpoint_path = Path(checkpoint_path)

        if urls is not None:
            self._urls_provided = urls
            # 清空pending队列，重新初始化
            while not self._pending_queue.empty():
                try:
                    self._pending_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            for t in list(self._tasks.values()):
                if t.status == TaskStatus.PENDING:
                    del self._tasks[t.url]
            self._init_tasks(urls)

        self._shutdown = False
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._completed_at = None
        self._worker_exc = None

        workers = [
            asyncio.create_task(self._worker(wid))
            for wid in range(self.concurrency)
        ]

        # 等待所有任务完成（计数器方式，避免 task_done() 的 cancel 问题）
        # 当 completed_count 达到 total_to_process 时，说明所有任务都处理完了
        while self._completed_count < self._total_to_process:
            if self._shutdown_event.is_set():
                break
            await asyncio.sleep(0.1)

        # 通知所有 worker 退出，并取消仍在等待的 worker
        self._shutdown_event.set()
        for w in workers:
            if not w.done():
                w.cancel()

        # 等待所有 worker 退出（最多 30s 安全网）
        try:
            await asyncio.wait_for(
                asyncio.gather(*workers, return_exceptions=True),
                timeout=30.0,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

        if self._worker_exc is not None:
            raise self._worker_exc

        self._shutdown = True
        self._completed_at = datetime.now(timezone.utc).isoformat()
        self._save_checkpoint()

        return self._tasks

    # ─── 工具方法 ──────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, int]:
        done = sum(1 for t in self._tasks.values() if t.status == TaskStatus.DONE)
        failed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED)
        pending = sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)
        running = sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING)
        skipped = sum(1 for t in self._tasks.values() if t.status == TaskStatus.SKIPPED)
        return {
            "total": len(self._tasks),
            "done": done,
            "failed": failed,
            "pending": pending,
            "running": running,
            "skipped": skipped,
        }

    def clear_checkpoint(self) -> None:
        """手动清理 checkpoint 文件（重新开始爬取）"""
        if self._checkpoint_path.exists():
            self._checkpoint_path.unlink()
        self._done_urls.clear()
        self._tasks.clear()
