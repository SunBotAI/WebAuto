"""
Core/ProxyPool/health.py — 代理健康追踪

每个 Proxy 在健康表里有自己的健康记录（独立于 Profile）：
  state: active / cooldown / banned
  consecutive_failures: 连续失败次数
  cooldown_until: unix timestamp（state=cooldown 时才有意义）
  last_check: 最近一次检查时间戳
  last_success_at: 最近一次成功时间戳
  last_failure_at: 最近一次失败时间戳
  latency_ms_avg: 平均延迟（最近 N 次的滑动平均）
  success_count: 累计成功次数
  failure_count: 累计失败次数

健康表持久化到 ~/.cache/webauto/proxies/proxy_health.json
原子写（与 ProfileStore 同样的 _atomic_write 模式）。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any


class ProxyHealthState(str, Enum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    BANNED = "banned"


@dataclass
class ProxyHealthRecord:
    """单个代理的健康记录。"""
    proxy_id: str
    state: str = ProxyHealthState.ACTIVE.value
    consecutive_failures: int = 0
    cooldown_until: Optional[float] = None
    last_check: Optional[float] = None
    last_success_at: Optional[float] = None
    last_failure_at: Optional[float] = None
    latency_ms_avg: float = 0.0
    latency_ms_last: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    last_error: str = ""

    def is_available(self, now: Optional[float] = None) -> bool:
        """当前是否可用（state=active 或 cooldown 已到期）。"""
        now = now or time.time()
        if self.state == ProxyHealthState.BANNED.value:
            return False
        if self.state == ProxyHealthState.COOLDOWN.value:
            if self.cooldown_until and now >= self.cooldown_until:
                # cooldown 到期，恢复 active
                self.state = ProxyHealthState.ACTIVE.value
                self.consecutive_failures = 0
                self.cooldown_until = None
                return True
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProxyHealthRecord":
        kwargs = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**kwargs)


class ProxyHealthStore:
    """代理健康表持久化。

    默认路径: ~/.cache/webauto/proxies/proxy_health.json
    格式: {proxy_id: ProxyHealthRecord dict, ...}
    """

    DEFAULT_PATH = Path.home() / ".cache" / "webauto" / "proxies" / "proxy_health.json"

    def __init__(self, path: Optional[Path] = None):
        self.path = path or self.DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ─── CRUD ─────────────────────────────────────────────────

    def load_all(self) -> Dict[str, ProxyHealthRecord]:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
        return {
            pid: ProxyHealthRecord.from_dict(rec)
            for pid, rec in raw.items()
            if isinstance(rec, dict)
        }

    def save_all(self, records: Dict[str, ProxyHealthRecord]) -> None:
        data = {pid: rec.to_dict() for pid, rec in records.items()}
        self._atomic_write(data)

    def get(self, proxy_id: str) -> ProxyHealthRecord:
        records = self.load_all()
        if proxy_id not in records:
            return ProxyHealthRecord(proxy_id=proxy_id)
        return records[proxy_id]

    def upsert(self, record: ProxyHealthRecord) -> None:
        records = self.load_all()
        records[record.proxy_id] = record
        self.save_all(records)

    def delete(self, proxy_id: str) -> None:
        records = self.load_all()
        records.pop(proxy_id, None)
        self.save_all(records)

    # ─── 原子写 ────────────────────────────────────────────────

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.path.parent,
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp.close()
            os.replace(tmp.name, str(self.path))
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass