"""通知模块.

支持企业微信 / 钉钉 / Telegram / 本地声音四种渠道。所有渠道统一通过
:meth:`Notifier.notify` 触发，内部并发执行且互不阻塞抢购主流程。

Webhook 请求都不抛异常到调用方——通知失败只记录日志，不影响抢购结果。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Optional

import httpx

from Core.Zhipu.config import Notification, NotifyType
from Core.Zhipu.logger import get_logger
from Core.Zhipu.scheduler import GrabSummary

log = get_logger()


class Notifier:
    """多渠道通知器。"""

    def __init__(self, cfg: Notification) -> None:
        self.cfg = cfg

    # ----------------------------------------------------------- 对外入口

    async def notify_summary(self, summary: GrabSummary) -> None:
        """根据抢购汇总结果发送通知。"""
        title = (
            "🎉 GLM Coding 抢购成功"
            if summary.any_success
            else "❌ GLM Coding 抢购失败"
        )
        lines = [
            title,
            f"成功 {summary.success_count}/{len(summary.results)} 个账号",
            "",
        ]
        for r in summary.results:
            status = "✅" if r.success else "❌"
            if r.success and r.order is not None:
                tier = r.order.raw.get("_selected_tier", "")
                amount = r.order.raw.get("_selected_pay_amount", "")
                tier_part = f"{tier} " if tier else ""
                amount_part = f" {amount}元" if amount else ""
                extra = f"抢到 {tier_part}订单 {r.order.order_id}{amount_part}（{r.latency_ms:.0f}ms）"
            elif r.success:
                extra = f"订单 {r.order.order_id if r.order else ''}（{r.latency_ms:.0f}ms）"
            else:
                extra = f"{r.error_type}: {r.error}"
            lines.append(f"{status} {r.account_name} — {extra}")
        text = "\n".join(lines)
        await self.notify(text, success=summary.any_success)

    async def notify(self, text: str, *, success: bool = False) -> None:
        """发送一条文本通知到所有已配置的渠道。"""
        tasks: list[Any] = []
        if self.cfg.type == NotifyType.WECHAT:
            tasks.append(self._send_wechat(text))
        elif self.cfg.type == NotifyType.DINGTALK:
            tasks.append(self._send_dingtalk(text))
        elif self.cfg.type == NotifyType.TELEGRAM:
            tasks.append(self._send_telegram(text))
        # 本地声音与渠道类型解耦：成功时响铃
        if success and self.cfg.sound_on_success:
            tasks.append(asyncio.to_thread(_beep))

        if not tasks:
            log.debug("未配置通知渠道，跳过通知")
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                log.warning(f"通知发送异常（已忽略）: {r}")

    # ----------------------------------------------------------- 各渠道

    async def _send_wechat(self, text: str) -> None:
        webhook = self.cfg.webhook
        if not webhook:
            return
        payload = {
            "msgtype": "text",
            "text": {"content": text},
        }
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.post(webhook, json=payload)
            log.debug(f"企业微信通知响应: {resp.status_code}")

    async def _send_dingtalk(self, text: str) -> None:
        webhook = self.cfg.webhook
        if not webhook:
            return
        payload = {
            "msgtype": "text",
            "text": {"content": text},
        }
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.post(webhook, json=payload)
            log.debug(f"钉钉通知响应: {resp.status_code}")

    async def _send_telegram(self, text: str) -> None:
        token = self.cfg.telegram_token
        chat_id = self.cfg.telegram_chat_id
        if not token or not chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.post(url, data={"chat_id": chat_id, "text": text})
            log.debug(f"Telegram 通知响应: {resp.status_code}")


# ---------------------------------------------------------------------------
# 本地声音
# ---------------------------------------------------------------------------


def _beep() -> None:
    """跨平台蜂鸣。Windows 用 winsound，其他平台用终端 BEL。"""
    if sys.platform == "win32":
        try:
            import winsound  # type: ignore[import-not-found]

            for _ in range(3):
                winsound.Beep(2000, 300)
            return
        except Exception:  # noqa: BLE001
            pass
    # 退路：输出 BEL 字符
    sys.stdout.write("\a")
    sys.stdout.flush()
