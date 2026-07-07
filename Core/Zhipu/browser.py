"""浏览器自动化备用方案.

当纯 HTTP 方案遭遇强反爬(JS 挑战、指纹校验)时,改用浏览器方案完成下单。

直接复用项目内的 StealthFetcher / HumanFetcher,自动获得:
- AntiDetect 注入(webdriver 隐藏 + fetch hook + WebGL 指纹随机化)
- TLS session 复用与连接池
- 人类模式下的贝塞尔鼠标轨迹(抢购场景下必备)

相比直接启动 Playwright,这套路径自动具备 WebAuto 项目已经实现的所有反检测能力。

典型用法::

    from Core.Zhipu.browser import run_browser_for_accounts
    results = await run_browser_for_accounts(config, time_sync, accounts)
    for name, pay_url in results:
        if pay_url:
            print(f"✅ {name}: {pay_url}")
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from Core.Fetchers import FetcherMode, create_fetcher
from Core.Fetchers.base import BaseFetcher
from Core.Zhipu.config import Account, AppConfig
from Core.Zhipu.constants import BASE_URL
from Core.Zhipu.logger import get_logger
from Core.Zhipu.timesync import TimeSync

log = get_logger()


# 智谱页面 DOM 选择器(2026-06 抓包确认,可能随前端改版变化)
SELECTOR_BUY_BUTTON = 'button:has-text("立即购买"), button:has-text("购买")'
SELECTOR_PLAN_TAB = 'div[role="tab"]:has-text("{plan}")'
URL_LANDING = f"{BASE_URL}/glm-coding"
URL_PAY_GLOB = "**/subscribe-pay**"


def _parse_cookie_header(cookie_str: str) -> list[dict[str, Any]]:
    """把 ``k1=v1; k2=v2`` 解析成 fetcher.set_cookies 接受的 dict。"""
    cookies: dict[str, str] = {}
    if not cookie_str:
        return cookies
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        cookies[k.strip()] = v.strip()
    return cookies


def _resolve_target_ts(config: AppConfig, ts: TimeSync) -> Optional[float]:
    """把 config.target_time 解析成服务器时间戳;空字符串返回 None(立即触发)。"""
    if not config.target_time:
        return None
    try:
        naive = datetime.strptime(config.target_time, "%Y-%m-%d %H:%M:%S")
        return (
            naive.timestamp()
            + ts.offset_s
            + config.time_offset_ms / 1000.0
        )
    except (ValueError, TypeError):
        log.warning(
            f"config.target_time 解析失败: {config.target_time!r},改为立即触发"
        )
        return None


class BrowserGrabber:
    """基于 StealthFetcher / HumanFetcher 的抢购器。

    Args:
        config: 全局配置。
        time_sync: 已校准的 TimeSync。
        mode: FetcherMode.STEALTH(headless) 或 HUMAN(显示窗口 + 人类行为)。
             默认 STEALTH,延迟更小;若反爬严重切到 HUMAN。
    """

    def __init__(
        self,
        config: AppConfig,
        time_sync: TimeSync,
        mode: FetcherMode = FetcherMode.STEALTH,
    ) -> None:
        self.config = config
        self.ts = time_sync
        self.mode = mode

    async def _make_fetcher(self, account: Account) -> BaseFetcher:
        """构造一个 fetcher,登录态已经注入。"""
        # 走 fetcher 工厂;不同 mode 对应不同的 Playwright 启动参数
        fetcher_config: dict[str, Any] = {
            "anti_detect": True,
            "headless": (self.mode == FetcherMode.STEALTH),
            "browser_type": "chromium",
        }
        fetcher = create_fetcher(self.mode.value, fetcher_config)
        await fetcher.init()
        # 注入 cookie / token,让服务器认得我们
        if account.cookie:
            fetcher.set_cookies(_parse_cookie_header(account.cookie))
        if account.token:
            # Human/Stealth fetcher 的 page 暴露 evaluate,我们用更稳的方式:
            # 通过 evaluate 注入 document.cookie 或在 headers 里带 Authorization
            # 当前 StealthFetcher 默认不内置 Authorization header 注入,
            # 这里只设 cookie;如果账号只有 token,需要扩展 fetcher 或先换 cookie。
            log.debug(
                f"[{account.name}] 仅 token 无 cookie,browser 模式可能需要登录"
            )
        return fetcher

    async def run(
        self, account: Account, target_server_ts: Optional[float] = None
    ) -> Optional[str]:
        """运行浏览器抢购,返回支付页 URL 或 None。

        Args:
            account: 账号配置(必须有 cookie 或 token)。
            target_server_ts: 目标触发时间戳;None 时从 config 推导。
        """
        if target_server_ts is None:
            target_server_ts = _resolve_target_ts(self.config, self.ts)

        fetcher = await self._make_fetcher(account)
        try:
            page = fetcher.page  # type: ignore[attr-defined]
            if page is None:
                raise RuntimeError(
                    f"Fetcher mode {self.mode.value} does not expose .page"
                )

            log.info(f"[{account.name}] 浏览器模式({self.mode.value}):打开落地页")
            await page.goto(URL_LANDING, wait_until="domcontentloaded")

            # 选择套餐档位(可能默认就在档位上,失败忽略)
            plan = self.config.target_plan.value
            try:
                tab = page.locator(SELECTOR_PLAN_TAB.format(plan=plan)).first
                await tab.click(timeout=5000)
                log.info(f"[{account.name}] 已选择套餐: {plan}")
            except Exception as e:  # noqa: BLE001
                log.warning(f"[{account.name}] 选择套餐失败(可能默认): {e}")

            # 等待到触发时间
            if target_server_ts is not None:
                wait_ms = max(
                    0, int((target_server_ts - self.ts.server_now()) * 1000)
                )
                log.info(f"[{account.name}] 浏览器等待触发: {wait_ms}ms")
                if wait_ms > 0:
                    # 用 NTP 校准后的两段式等待(精度 ±5ms),优于 page.wait_for_timeout
                    await self.ts.sleep_until(target_server_ts)

            # 点击购买
            import time as _time
            t0 = _time.perf_counter()
            try:
                await page.click(SELECTOR_BUY_BUTTON, timeout=5000)
            except Exception as e:  # noqa: BLE001
                log.error(f"[{account.name}] 点击购买按钮失败: {e}")
                return None

            # 等待跳转到支付页
            try:
                await page.wait_for_url(URL_PAY_GLOB, timeout=15000)
            except Exception:  # noqa: BLE001
                log.warning(f"[{account.name}] 未跳转到支付页,尝试继续")

            latency = (_time.perf_counter() - t0) * 1000
            pay_url = page.url
            log.success(
                f"[{account.name}] 浏览器下单完成,支付页: {pay_url} "
                f"({latency:.0f}ms)"
            )

            # 非 stealth(headless=False)模式保留窗口供手动支付
            if not fetcher_config_headless(self):
                log.info("浏览器保持打开,请在窗口内完成支付;30s 后自动关闭")
                await asyncio.sleep(30)
            return pay_url
        finally:
            await fetcher.close()


def fetcher_config_headless(grabber: "BrowserGrabber") -> bool:
    """小工具:从 grabber 的 mode 推断 headless。"""
    return grabber.mode == FetcherMode.STEALTH


async def run_browser_for_accounts(
    config: AppConfig,
    time_sync: TimeSync,
    accounts: list[Account],
    *,
    mode: FetcherMode = FetcherMode.STEALTH,
) -> list[tuple[str, Optional[str]]]:
    """并发对多账号执行浏览器抢购,返回 [(account_name, pay_url), ...]。

    Args:
        config: 全局配置。
        time_sync: NTP 校准后的 TimeSync。
        accounts: 账号列表。
        mode: FetcherMode.STEALTH(默认,headless) 或 HUMAN(显示窗口 + 人类行为)。
    """
    grabber = BrowserGrabber(config, time_sync, mode=mode)
    sem = asyncio.Semaphore(config.max_concurrent)

    async def _one(a: Account) -> tuple[str, Optional[str]]:
        async with sem:
            try:
                url = await grabber.run(a)
                return (a.name, url)
            except Exception as e:  # noqa: BLE001
                log.error(f"[{a.name}] 浏览器抢购异常: {e}")
                return (a.name, None)

    return await asyncio.gather(*(_one(a) for a in accounts))