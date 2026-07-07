"""
高精度时间同步模块
基于 GlmCodingGrabber 的 NTP 时间同步方案,两段式等待

主要功能:
1. NTP 多次采样取中位数,过滤网络抖动
2. 两段式等待(粗 sleep + busy spin)保证毫秒级精度
3. 支持任意目标时间戳触发
"""
import time
import asyncio
import statistics
from typing import Optional, List
from dataclasses import dataclass
import ntplib


@dataclass
class TimeSyncStats:
    """同步统计信息"""
    ntp_server: str
    samples: int
    success_samples: int
    offset_ms: float           # 本地时钟 vs NTP 偏移(毫秒)
    jitter_ms: float           # 采样抖动(最大-最小)
    latency_avg_ms: float      # 平均网络延迟


class TimeSync:
    """高精度时间同步器"""
    
    DEFAULT_NTP_SERVERS = [
        "ntp.aliyun.com",
        "ntp.tencent.com",
        "cn.pool.ntp.org",
        "time.windows.com",
        "time.apple.com",
    ]
    
    def __init__(
        self,
        ntp_server: Optional[str] = None,
        samples: int = 5,
        timeout: float = 3.0
    ):
        """
        初始化时间同步器
        
        Args:
            ntp_server: NTP 服务器地址,默认自动选择最快的
            samples: 采样次数
            timeout: 单次采样超时(秒)
        """
        self.ntp_server = ntp_server
        self.samples = samples
        self.timeout = timeout
        self.offset_s: float = 0.0  # 本地时钟偏移(秒),local + offset = server
        self._calibrated: bool = False
        self._stats: Optional[TimeSyncStats] = None
        
    async def calibrate(self) -> TimeSyncStats:
        """
        执行 NTP 校准(异步,不阻塞事件循环)
        
        Returns:
            TimeSyncStats 统计信息
        """
        loop = asyncio.get_event_loop()
        
        # 自动选择最快的 NTP 服务器
        if not self.ntp_server:
            self.ntp_server = await self._find_fastest_server()
            
        offsets: List[float] = []
        latencies: List[float] = []
        failures = 0
        
        for i in range(self.samples):
            try:
                t0 = time.time()
                offset = await loop.run_in_executor(
                    None,
                    self._single_ntp_query,
                    self.ntp_server
                )
                t1 = time.time()
                
                offsets.append(offset)
                latencies.append(t1 - t0)
                
                # 采样间隔,避免打满 NTP 服务器
                if i < self.samples - 1:
                    await asyncio.sleep(0.05)
                    
            except Exception as e:
                failures += 1
                print(f"[TimeSync] NTP sample {i+1} failed: {e}")
                
        if not offsets:
            raise RuntimeError(f"All NTP samples failed ({failures}/{self.samples})")
            
        # 取中位数作为最终偏移(过滤抖动)
        self.offset_s = statistics.median(offsets)
        spread = max(offsets) - min(offsets) if len(offsets) > 1 else 0.0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        
        self._stats = TimeSyncStats(
            ntp_server=self.ntp_server,
            samples=self.samples,
            success_samples=len(offsets),
            offset_ms=self.offset_s * 1000,
            jitter_ms=spread * 1000,
            latency_avg_ms=avg_latency * 1000
        )
        
        self._calibrated = True
        
        print(
            f"[TimeSync] Calibrated with {self.ntp_server}: "
            f"offset={self._stats.offset_ms:+.1f}ms, "
            f"jitter={self._stats.jitter_ms:.1f}ms, "
            f"latency={self._stats.latency_avg_ms:.1f}ms"
        )
        
        return self._stats
        
    async def _find_fastest_server(self) -> str:
        """自动选择最快的 NTP 服务器"""
        loop = asyncio.get_event_loop()
        
        async def probe(server: str) -> float:
            try:
                t0 = time.time()
                await loop.run_in_executor(None, self._single_ntp_query, server)
                return time.time() - t0
            except:
                return float('inf')
                
        # 并发探测所有服务器
        probes = [probe(s) for s in self.DEFAULT_NTP_SERVERS]
        results = await asyncio.gather(*probes, return_exceptions=True)
        
        # 选最快的
        best_idx = 0
        best_latency = float('inf')
        for i, r in enumerate(results):
            if isinstance(r, float) and r < best_latency:
                best_latency = r
                best_idx = i
                
        if best_latency == float('inf'):
            raise RuntimeError("No available NTP servers")
            
        return self.DEFAULT_NTP_SERVERS[best_idx]
        
    def _single_ntp_query(self, server: str) -> float:
        """单次 NTP 查询(同步)"""
        client = ntplib.NTPClient()
        resp = client.request(server, version=3, timeout=self.timeout)
        return float(resp.offset)
        
    @property
    def server_now(self) -> float:
        """当前服务器时间戳(秒)"""
        if not self._calibrated:
            raise RuntimeError("TimeSync not calibrated, call calibrate() first")
        return time.time() + self.offset_s
        
    @property
    def server_now_ms(self) -> int:
        """当前服务器时间戳(毫秒)"""
        return int(self.server_now * 1000)
        
    def local_to_server(self, local_ts: float) -> float:
        """本地时间转服务器时间"""
        return local_ts + self.offset_s
        
    def server_to_local(self, server_ts: float) -> float:
        """服务器时间转本地时间"""
        return server_ts - self.offset_s
        
    async def sleep_until_server_time(
        self,
        target_server_ts: float,
        precision_ms: int = 5,
        sleep_chunk_ms: int = 50
    ) -> None:
        """
        异步等待直到服务器时间到达目标时间戳
        
        两段式等待:
        1. 粗等待:asyncio.sleep,每次最多 sleep_chunk_ms 毫秒
        2. 忙等待:busy spin,直到到达精度范围内
        
        Args:
            target_server_ts: 目标服务器时间戳(秒)
            precision_ms: 忙等待进入阈值(毫秒)
            sleep_chunk_ms: 粗等待每次休眠时长(毫秒)
        """
        if not self._calibrated:
            await self.calibrate()
            
        precision = precision_ms / 1000.0
        chunk = sleep_chunk_ms / 1000.0
        
        # 阶段 1: 粗等待
        while True:
            remaining = target_server_ts - self.server_now
            if remaining <= precision:
                break
            if remaining <= 0:
                return
            # 留一定余量,避免 sleep 过久错过时间点
            sleep_time = min(chunk, max(0.0, remaining - precision * 2))
            await asyncio.sleep(sleep_time)
            
        # 阶段 2: 忙等待(CPU 自旋,保证最高精度)
        while self.server_now < target_server_ts:
            pass
            
    async def sleep_until_datetime(
        self,
        target_datetime,  # datetime.datetime 对象
        precision_ms: int = 5
    ) -> None:
        """
        等待直到指定的 datetime(服务器时间)
        
        Args:
            target_datetime: 目标时间(datetime,必须带时区或 UTC)
            precision_ms: 精度(毫秒)
        """
        import datetime
        
        if target_datetime.tzinfo is None:
            # 假设是本地时间,转 UTC 时间戳
            target_ts = target_datetime.timestamp()
        else:
            # 带时区,直接取时间戳
            target_ts = target_datetime.timestamp()
            
        await self.sleep_until_server_time(target_ts, precision_ms)
        
    async def countdown(
        self,
        seconds: float,
        precision_ms: int = 5
    ) -> None:
        """
        倒计时(基于服务器时间)
        
        Args:
            seconds: 倒计时秒数
            precision_ms: 精度(毫秒)
        """
        target = self.server_now + seconds
        await self.sleep_until_server_time(target, precision_ms)
        
    @property
    def stats(self) -> Optional[TimeSyncStats]:
        """获取统计信息"""
        return self._stats
        
    @property
    def calibrated(self) -> bool:
        """是否已校准"""
        return self._calibrated


# ===== 便捷函数 =====

async def create_timesync(
    ntp_server: Optional[str] = None,
    samples: int = 5
) -> TimeSync:
    """
    便捷函数:创建并校准时间同步器
    
    Args:
        ntp_server: NTP 服务器地址
        samples: 采样次数
        
    Returns:
        已校准的 TimeSync 对象
    """
    ts = TimeSync(ntp_server, samples)
    await ts.calibrate()
    return ts


# ===== 同步版本(非 async 环境使用)=====

class TimeSyncSync(TimeSync):
    """同步版本的时间同步器"""
    
    def calibrate(self) -> TimeSyncStats:
        """同步校准"""
        offsets: List[float] = []
        latencies: List[float] = []
        failures = 0
        
        for i in range(self.samples):
            try:
                t0 = time.time()
                offset = self._single_ntp_query(self.ntp_server or self.DEFAULT_NTP_SERVERS[0])
                t1 = time.time()
                
                offsets.append(offset)
                latencies.append(t1 - t0)
                
                if i < self.samples - 1:
                    time.sleep(0.05)
                    
            except Exception as e:
                failures += 1
                print(f"[TimeSync] NTP sample {i+1} failed: {e}")
                
        if not offsets:
            raise RuntimeError(f"All NTP samples failed ({failures}/{self.samples})")
            
        self.offset_s = statistics.median(offsets)
        spread = max(offsets) - min(offsets) if len(offsets) > 1 else 0.0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        
        self._stats = TimeSyncStats(
            ntp_server=self.ntp_server or self.DEFAULT_NTP_SERVERS[0],
            samples=self.samples,
            success_samples=len(offsets),
            offset_ms=self.offset_s * 1000,
            jitter_ms=spread * 1000,
            latency_avg_ms=avg_latency * 1000
        )
        
        self._calibrated = True
        return self._stats
        
    def sleep_until_server_time(
        self,
        target_server_ts: float,
        precision_ms: int = 5,
        sleep_chunk_ms: int = 50
    ) -> None:
        """同步等待"""
        if not self._calibrated:
            self.calibrate()
            
        precision = precision_ms / 1000.0
        chunk = sleep_chunk_ms / 1000.0
        
        # 阶段 1: 粗等待
        while True:
            remaining = target_server_ts - self.server_now
            if remaining <= precision:
                break
            if remaining <= 0:
                return
            sleep_time = min(chunk, max(0.0, remaining - precision * 2))
            time.sleep(sleep_time)
            
        # 阶段 2: 忙等待
        while self.server_now < target_server_ts:
            pass
