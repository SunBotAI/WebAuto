"""NTP 时间同步模块.

负责计算本地时钟与服务器的偏移量（offset），提供：

- :func:`get_ntp_offset`    — 单次查询偏移
- :func:`calibrate_offset`  — 多次查询取中位数，过滤抖动
- :class:`TimeSync`         — 持有校准结果，提供 ``server_now()`` / ``sleep_until()``

偏移定义（与 ntplib 一致）::

    offset = ((t1 - t0) + (t2 - t3)) / 2

其中 t0=请求发送, t1=服务端接收, t2=服务端发送, t3=本地接收。
正值表示本地时钟比服务器慢（落后），需要把目标触发时间往前推。
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass

import ntplib

from Core.Zhipu.logger import get_logger

log = get_logger()


def get_ntp_offset(server: str, timeout: float = 3.0) -> float:
    """单次向 NTP 服务器查询本地时钟偏移（秒）。

    Raises:
        ntplib.NTPException: 网络或服务异常。
    """
    client = ntplib.NTPClient()
    resp = client.request(server, version=3, timeout=timeout)
    return float(resp.offset)


def calibrate_offset(
    server: str, *, samples: int = 5, timeout: float = 3.0
) -> float:
    """多次采样取中位数，过滤网络抖动。返回偏移秒数。"""
    offsets: list[float] = []
    failures = 0
    for i in range(max(1, samples)):
        try:
            offsets.append(get_ntp_offset(server, timeout=timeout))
        except (ntplib.NTPException, OSError) as e:
            failures += 1
            log.warning(f"NTP 第 {i+1}/{samples} 次采样失败: {e}")
        if i < samples - 1:
            time.sleep(0.05)
    if not offsets:
        raise RuntimeError(
            f"NTP 同步全部失败 ({failures}/{samples})，请检查网络或 ntp_server 配置"
        )
    return statistics.median(offsets)


@dataclass(slots=True)
class TimeSyncStats:
    samples: int
    success_samples: int
    offset_ms: float
    jitter_ms: float
    latency_avg_ms: float
    ntp_server: str


@dataclass
class TimeSync:
    """持有 NTP 校准结果,提供 server_now / sleep_until。

    用法::

        ts = build_time_sync("ntp.aliyun.com")
        ts.sleep_until(target_ts)   # 等待到目标服务器时间戳
    """

    offset_s: float = 0.0  # 正值表示本地慢,local + offset = server

    def server_now(self) -> float:
        """当前服务器时间戳（秒）。"""
        return time.time() + self.offset_s

    def sleep_until(self, target_server_ts: float, *, precision_ms: int = 5, chunk_ms: int = 50) -> None:
        """两段式等待：粗 sleep + busy spin，精度 ~5ms。"""
        precision = precision_ms / 1000.0
        chunk = chunk_ms / 1000.0
        # 阶段一:粗等待
        while True:
            remaining = target_server_ts - self.server_now()
            if remaining <= precision or remaining <= 0:
                break
            sleep_time = min(chunk, max(0.0, remaining - precision * 2))
            time.sleep(sleep_time)
        # 阶段二:忙等
        while self.server_now() < target_server_ts:
            pass


def build_time_sync(server: str = "", *, samples: int = 5) -> TimeSync:
    """工厂方法:执行 NTP 校准并返回 :class:`TimeSync`。

    Args:
        server: NTP 服务器地址。传空字符串或 None 时,自动探测多个公共 NTP
                并选最快的(复用了 WebAuto 原生 Core.TimeSync 的探测逻辑)。
        samples: 采样次数。
    """
    if not server:
        # server 空 → 自动选最快,复用项目里更强的 TimeSync
        from Core.TimeSync import TimeSync as CoreTimeSync
        return _sync_via_core(CoreTimeSync, samples)

    offset = calibrate_offset(server, samples=samples)
    return TimeSync(offset_s=offset)


def _sync_via_core(core_cls, samples: int) -> TimeSync:
    """在 CLI 顶层调用 Core.TimeSync.calibrate(),把结果转成本模块的 TimeSync。"""
    cts = core_cls(samples=samples)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 已在 async 上下文里(比如 orchestrator 异步跑) → 抛错让上层 await
            raise RuntimeError(
                "build_time_sync with auto-select must be awaited from async context"
            )
        stats = loop.run_until_complete(cts.calibrate())
    except RuntimeError:
        # 没 loop / loop 已 running 都重走 asyncio.run
        stats = asyncio.run(cts.calibrate())
    return TimeSync(offset_s=stats.offset_ms / 1000.0)
