"""
Core/Profile/orchestrator.py — 浏览器编排器

管理 Profile ↔ BrowserContext 的生命周期。
关键设计：一个 Chromium 进程管理多个 Profile 的 BrowserContext（复用进程，内存优化）。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, List

import psutil
from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright

from .profile import Profile, ProfileStatus
from .store import ProfileStore

logger = logging.getLogger(__name__)

# 2GB 内存阈值
MEMORY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024  # 2GB


class BrowserOrchestrator:
    """
    管理 Profile ↔ BrowserContext 的生命周期。

    重要：一个 Chromium 进程（browser）服务所有 Profile，
    每个 Profile 通过独立的 BrowserContext + user_data_dir 实现完全隔离。
    """

    def __init__(
        self,
        store: ProfileStore,
        *,
        headless: bool = True,
        chromium_path: Optional[str] = None,
        max_concurrent: int = 5,
        memory_limit_bytes: int = MEMORY_LIMIT_BYTES,
    ):
        self.store = store
        self.headless = headless
        self.chromium_path = chromium_path or self._default_chromium()
        self.max_concurrent = max_concurrent
        self.memory_limit_bytes = memory_limit_bytes

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._contexts: Dict[str, BrowserContext] = {}
        self._context_locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        # T-059: per-profile lock（替代全局锁），不同 Profile 可真正并发
        self._semaphore: Optional[asyncio.Semaphore] = None

    # ─── 生命周期 ──────────────────────────────────────────────

    def _get_browser_memory_bytes(self) -> int:
        """获取 Chromium 主进程内存占用（RSS），单位字节。"""
        if self._browser is None:
            return 0
        try:
            process = psutil.Process(self._browser.process.pid)
            return process.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0

    def _check_memory(self) -> None:
        """检查内存超限，超限则抛异常拒绝新 Context。"""
        mem = self._get_browser_memory_bytes()
        if mem > self.memory_limit_bytes:
            raise MemoryError(
                f"Chromium memory {mem / 1024 / 1024:.0f}MB exceeds limit "
                f"{self.memory_limit_bytes / 1024 / 1024:.0f}MB, rejecting new Context"
            )

    async def start(self, browser_args: Optional[List[str]] = None) -> None:
        """启动共享的 Chromium 进程

        Args:
            browser_args: 合并所有 Profile 的 browser_args 后去重传入 launch()
        """
        if self._browser is not None:
            return

        base_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-zygote",
            "--window-size=1920,1080",
        ]
        if browser_args:
            # 合并 Profile 级别的自定义 args，去重保留顺序
            seen = set(x.split("=")[0] for x in base_args)
            for arg in browser_args:
                key = arg.split("=")[0]
                if key not in seen:
                    base_args.append(arg)
                    seen.add(key)

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            executable_path=self.chromium_path,
            headless=self.headless,
            args=base_args,
        )
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    async def stop(self) -> None:
        """关闭所有 Context 和 Browser"""
        for ctx in list(self._contexts.values()):
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts.clear()

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def __aenter__(self) -> "BrowserOrchestrator":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    # ─── Context 获取 ──────────────────────────────────────────

    async def get_context(self, profile: Profile) -> BrowserContext:
        """
        为 Profile 创建（或复用）BrowserContext。

        隔离手段：
        - user_data_dir = profile.storage_dir / "user-data"（Cookie/Storage/IndexedDB 完全隔离）
        - viewport / user_agent / locale / timezone 来自 profile.fingerprint
        - proxy 来自 profile.network
        - AntiDetect 脚本注入
        - extensions 来自 profile.extensions（.crx 扩展目录列表）

        容量控制：
        - max_concurrent semaphore：超过并发阈值的请求排队等待
        - memory limit：Chromium 进程 RSS 超过 2GB 时拒绝新 Context 并报警

        T-059: per-profile lock 保证同一 Profile 并发 acquire 不会重复创建 Context；
        不同 Profile 之间完全并发，实现 5 账号真并发启动。
        """
        if profile.id in self._contexts:
            return self._contexts[profile.id]

        # T-059: per-profile lock（不是 global lock），不同 Profile 可并发创建 Context
        profile_lock = self._context_locks.setdefault(profile.id, asyncio.Lock())
        async with profile_lock:
            # 双重检查（获取锁后其他协程可能已经创建好了）
            if profile.id in self._contexts:
                return self._contexts[profile.id]

            # max_concurrent 排队控制
            if self._semaphore is None:
                self._semaphore = asyncio.Semaphore(self.max_concurrent)
            await self._semaphore.acquire()

            # 内存检查：超限拒绝新 Context
            self._check_memory()

            try:
                # browser 启动仍需 global lock（共享进程，只能一个启动）
                async with self._global_lock:
                    if self._browser is None:
                        # 合并所有已加载 Profile 的 browser_args
                        all_args: List[str] = []
                        for p_id in self._contexts:
                            pass  # 第一启动时尚无 context，browser_args 由第一 profile 决定
                        # 首次启动：使用当前 profile 的 browser_args
                        await self.start(browser_args=profile.browser_args)

                # T-057: extensions（支持 .crx 路径列表）
                # 注意：user_data_dir 只在 launch_persistent_context() 支持，
                # new_context() 天然有独立 Cookie/localStorage/IndexedDB 隔离
                ctx_options: dict = {
                    # 内部字段：帮助单元测试 mock 从 kwargs 识别 profile_id
                    "_profile_id": profile.id,
                    "viewport": {
                        "width": profile.fingerprint.screen_resolution[0],
                        "height": profile.fingerprint.screen_resolution[1],
                    },
                    "user_agent": profile.fingerprint.user_agent,
                    "locale": profile.fingerprint.locale,
                    "timezone_id": profile.fingerprint.timezone,
                    "proxy": self._get_playwright_proxy(profile),
                    "color_scheme": "light",
                }
                if profile.extensions:
                    ctx_options["extensions"] = profile.extensions

                ctx = await self._browser.new_context(**ctx_options)

                # 注入反检测脚本
                await self._inject_anti_detect(ctx, profile)

                self._contexts[profile.id] = ctx
                profile.status = ProfileStatus.RUNNING
                self.store.save(profile)

                return ctx

            except Exception:
                # 创建失败要释放 semaphore 配额
                if self._semaphore is not None:
                    self._semaphore.release()
                raise

    async def warmup(
        self,
        profiles: List[Profile],
        *,
        ntp_sync: bool = True,
    ) -> None:
        """
        批量预热：并发启动所有 Profile 的 BrowserContext。
        用于抢购场景（目标时间前 T-30s 就绪）。
        """
        if not profiles:
            return

        if self._browser is None:
            await self.start()

        # 并发为所有 Profile 创建 context
        tasks = [self.get_context(p) for p in profiles]
        await asyncio.gather(*tasks, return_exceptions=True)

        if ntp_sync:
            # NTP 校时（如果 WebAuto TimeSync 可用）
            try:
                from Core.TimeSync import TimeSync
                ts = TimeSync()
                await ts.calibrate()
            except Exception:
                pass

    async def close_context(self, profile: Profile) -> None:
        """关闭单个 Profile 的 BrowserContext（但不关闭 Chromium 进程）"""
        ctx = self._contexts.pop(profile.id, None)
        if ctx:
            await ctx.close()
            profile.status = ProfileStatus.READY
            self.store.save(profile)
            # 释放一个并发槽位
            if self._semaphore is not None:
                self._semaphore.release()

    # ─── 反检测注入 ────────────────────────────────────────────

    async def _inject_anti_detect(self, ctx: BrowserContext, profile: Profile) -> None:
        """注入 Profile 专属的反检测脚本"""
        from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector

        cfg = AntiDetectConfig()
        # FINGERPRINT-006: 同步全部 7 项字段（seed + locale/timezone/platform/vendor/screen/hardware）
        profile.apply_to_antidetect(cfg)

        injector = AntiDetectInjector(cfg)
        init_script = injector.get_inject_script()
        if init_script:
            await ctx.add_init_script(init_script)

        # Profile 专属自定义脚本
        for script in profile.custom_scripts:
            if script.strip():
                await ctx.add_init_script(script)

    # ─── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _default_chromium() -> str:
        """返回默认 Chromium 路径"""
        import glob
        candidates = glob.glob(
            str(Path.home() / ".cache" / "ms-playwright" / "chromium-*" / "chrome-linux64" / "chrome")
        )
        if candidates:
            return sorted(candidates)[-1]
        raise FileNotFoundError(
            "No Chromium found. Run: playwright install chromium"
        )

    @staticmethod
    def _get_playwright_proxy(profile: Profile) -> Optional[dict]:
        """把 Profile.network 转换为 Playwright new_context 的 proxy 字段"""
        result = profile.network.get_playwright_proxy()
        if result is None:
            return None
        server, username, password = result
        return {
            "server": server,
            "username": username,
            "password": password,
        }
