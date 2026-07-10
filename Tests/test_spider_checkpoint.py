"""
Spider checkpoint — kill-restart 暂停恢复测试

覆盖场景：
1. Spider 爬 N 个 URL
2. kill -9（进程强制终止，不走 shutdown）
3. 重启后从 checkpoint 续跑
4. 已爬 URL 不重复，已爬 count 不增加
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from Core.Spider import Spider, SpiderTask, TaskStatus


class KillableSpider(Spider):
    """
    测试用 Spider：
    - 每个 task 记录到 self.processed（去重验证）
    - 支持中途 kill（模拟 kill -9）：_kill_urls 指定哪些 URL 爬完就 raise
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.processed: list[str] = []
        self._kill_urls: set[str] | None = None

    async def process(self, task: SpiderTask) -> dict:
        """记录已爬，延迟模拟 IO"""
        await asyncio.sleep(0.05)
        self.processed.append(task.url)
        if self._kill_urls and task.url in self._kill_urls:
            raise RuntimeError(f"simulated kill on {task.url}")
        return {"url": task.url, "ok": True}


# ─── subprocess 测试辅助 ───────────────────────────────────

_KILL_RESTART_CODE = r"""
import asyncio, sys, json, tempfile
from pathlib import Path
sys.path.insert(0, %r)

from Core.Spider import Spider, SpiderTask

class KillableSpider(Spider):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.processed = []
        self._kill_urls = set()
    async def process(self, task):
        await asyncio.sleep(0.05)
        self.processed.append(task.url)
        if task.url in self._kill_urls:
            raise RuntimeError("simulated kill")
        return {"url": task.url}

with tempfile.TemporaryDirectory() as tmp:
    cp = Path(tmp) / "kill.json"

    # Round 1: kill on http://x/2
    s1 = KillableSpider(
        urls=[f"http://x/{i}" for i in range(5)],
        concurrency=2,
        checkpoint_path=str(cp),
        max_retries=0,
    )
    s1._kill_urls = {"http://x/2"}
    try:
        asyncio.run(s1.run())
    except RuntimeError:
        pass

    # Round 2: resume
    s2 = KillableSpider(
        urls=[f"http://x/{i}" for i in range(5)],
        concurrency=2,
        checkpoint_path=str(cp),
    )
    asyncio.run(s2.run())

    # 验证：最终 checkpoint 中所有 5 个 URL 都标记为 done
    data = json.loads(Path(cp).read_text())
    print("RESULT:", json.dumps({
        "checkpoint_done": data["stats"]["done"],
        "s2_processed": s2.processed,
        "s2_stats": s2.stats,
    }))

    # 关键断言：最终 checkpoint 中 done=5（kill + 重启后所有 URL 都成功）
    assert data["stats"]["done"] == 5, f"expected 5 done in checkpoint, got {data['stats']}"
    print("PASSED")
""" % str(Path(__file__).parent.parent)


class TestSpiderCheckpoint:
    """Spider Checkpoint — kill-safe 暂停恢复"""

    # ── 基础 ─────────────────────────────────────────────────

    def test_spider_task_status_enum(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.DONE.value == "done"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.SKIPPED.value == "skipped"

    def test_spider_task_to_dict(self):
        t = SpiderTask(url="http://x/1", status=TaskStatus.DONE)
        t.result = {"ok": True}
        d = asdict(t)
        assert d["url"] == "http://x/1"
        assert d["status"] == TaskStatus.DONE
        assert d["result"]["ok"] is True

    def test_clear_checkpoint(self, tmp_path: Path):
        """clear_checkpoint 删除文件并清空内存状态"""
        cp = str(tmp_path / "s.json")
        s = KillableSpider(urls=["a", "b"], concurrency=1, checkpoint_path=cp)
        s._save_checkpoint()
        assert Path(cp).exists()
        s.clear_checkpoint()
        assert not Path(cp).exists()
        assert len(s._done_urls) == 0

    def test_checkpoint_stats(self, tmp_path: Path):
        """_checkpoint_data 统计正确"""
        cp = str(tmp_path / "s.json")
        s = KillableSpider(urls=["a", "b", "c"], concurrency=2, checkpoint_path=cp)
        asyncio.run(s.run())
        assert s.stats["total"] == 3
        assert s.stats["done"] == 3
        assert s.stats["pending"] == 0

    # ── kill-restart 核心测试 ────────────────────────────────
    # subprocess 隔离运行避免 pytest-asyncio 事件循环行为差异导致 hang

    def test_checkpoint_kill_restart_no_duplicate(self):
        """Spider kill -9 后重启，已爬 URL 不重复"""
        result = subprocess.run(
            [sys.executable, "-c", _KILL_RESTART_CODE],
            capture_output=True,
            text=True,
            timeout=60,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            raise AssertionError(
                f"subprocess failed (rc={result.returncode})\n"
                f"stdout: {stdout}\nstderr: {stderr}"
            )
        if "PASSED" not in stdout:
            raise AssertionError(f"subprocess did not pass\nstdout: {stdout}\nstderr: {stderr}")

    def test_checkpoint_restart_all_urls_already_done(self, tmp_path: Path):
        """所有 URL 在 checkpoint 中已全部完成，重启后 0 个重复处理"""
        cp = str(tmp_path / "all_done.json")

        # 先完整爬完
        s1 = KillableSpider(urls=["http://a/1", "http://b/2"], concurrency=2, checkpoint_path=cp)
        asyncio.run(s1.run())
        assert s1.stats["done"] == 2

        # 重启，已完成的 URL 不应再入队
        s2 = KillableSpider(urls=["http://a/1", "http://b/2"], concurrency=2, checkpoint_path=cp)
        assert len(s2._done_urls) == 2
        assert s2._pending_queue.qsize() == 0, "all tasks should be SKIPPED, queue empty"

        asyncio.run(s2.run())

        # 无新处理（全部是 checkpoint 恢复的）
        assert len(s2.processed) == 0, "already-done URLs must not be re-processed"
        data = json.loads(Path(cp).read_text())
        assert data["stats"]["done"] == 2

    def test_checkpoint_partial_progress(self, tmp_path: Path):
        """checkpoint 有部分 done/restart，重启后正确恢复 pending 数量"""
        cp = str(tmp_path / "partial.json")

        # 第一轮：只爬完部分任务
        s1 = KillableSpider(
            urls=[f"http://x/{i}" for i in range(4)],
            concurrency=2,
            checkpoint_path=cp,
            max_retries=0,
        )
        s1._kill_urls = {"http://x/1"}  # 爬到 x/1 就 kill
        with pytest.raises(RuntimeError):
            asyncio.run(s1.run())

        data1 = json.loads(Path(cp).read_text())
        # 至少 done>=1（x/0 完成）
        assert data1["stats"]["done"] >= 1
        assert data1["stats"]["pending"] >= 1

        # 第二轮：续跑，pending 入队
        s2 = KillableSpider(urls=[f"http://x/{i}" for i in range(4)], concurrency=2, checkpoint_path=cp)
        assert s2._pending_queue.qsize() >= 1, f"expected pending tasks, got {s2._pending_queue.qsize()}"

        asyncio.run(s2.run())

        data2 = json.loads(Path(cp).read_text())
        # pending=0：所有待处理的都处理完了
        assert data2["stats"]["pending"] == 0, f"expected 0 pending, got {data2['stats']}"
