r"""GLM Coding 套餐持续探测:页面刷新直到"售罄"消失,触发抢单.

工作流程:
1. 持续刷新 https://bigmodel.cn/glm-coding?plantype=personal
2. 每 N 秒检查页面 DOM,看"暂时售罄"是否消失
3. 消失 → 触发回调(发 webhook / 跑命令 / 切到你的抢单脚本)
4. 整个过程实时输出探测日志

## 用法
    # 默认每 3 秒刷一次,默认探 Max 套餐
    .venv-fix/bin/python Tools/zhipu_watch.py

    # 自定义间隔 + 套餐 + 回调
    .venv-fix/bin/python Tools/zhipu_watch.py \\
      --interval 5 \\
      --on-available "echo 抢到了! && python Tools/console.py"

环境:
    需要 Chrome DevTools 在跑(bash Tools/cdp_launch.sh)
"""
import argparse
import asyncio
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


SOLD_OUT_MARKERS = ["暂时售罄", "已售罄", "soldOut", "sold_out"]
# 严格匹配"立即购买"按钮文本(避免 FAQ 里"限量购买"误匹配)
ANY_AVAILABLE_MARKER = ["立即购买", "去购买", "购买套餐"]


def _print(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def _page_has_sold_out(body: str) -> bool:
    """页面是否仍显示售罄。"""
    return any(m in body for m in SOLD_OUT_MARKERS)


def _page_has_buy_button(body: str) -> bool:
    """页面是否显示真正的"购买"按钮。

    通过 "立即购买" / "去购买" / "购买套餐" 这些按钮文案判断,
    避免 FAQ 里 "限量购买" 这种误匹配。
    """
    return any(m in body for m in ANY_AVAILABLE_MARKER)


async def run(args) -> int:
    from playwright.async_api import async_playwright

    url = "https://bigmodel.cn/glm-coding?plantype=personal"
    interval = args.interval
    max_seconds = args.max_seconds or 0  # 0 = 无限

    print(f"探测目标: {url}")
    print(f"刷新间隔: {interval}s")
    print(f"最大时长: {max_seconds}s ({'无限' if not max_seconds else '到时自动停'})")
    if args.on_available:
        print(f"触发命令: {args.on_available}")
    print("按 Ctrl+C 中断")
    print("---")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        try:
            # 找 bigmodel.cn tab,没有就新建
            page = None
            for pg in browser.contexts[0].pages:
                if "bigmodel.cn" in pg.url:
                    page = pg
                    break
            if page is None:
                page = await browser.contexts[0].new_page()
                await page.goto(url)
            else:
                await page.bring_to_front()
                await page.goto(url)

            _print(f"在 tab [{page.url[:60]}] 启动探测")

            start = time.time()
            attempt = 0
            # 状态枚举:loading / sold_out / available / unknown
            history: list[str] = []

            while True:
                attempt += 1
                elapsed = int(time.time() - start)
                if max_seconds and elapsed > max_seconds:
                    _print(f"达到 {max_seconds}s 上限,停止")
                    break

                body = await page.evaluate(
                    "() => document.body ? document.body.innerText : ''"
                )

                # 三态判断(优先级:available > sold_out > loading)
                if _page_has_buy_button(body) and not _page_has_sold_out(body):
                    state = "available"  # 🟢 可买
                elif _page_has_sold_out(body):
                    state = "sold_out"  # 🔴 售罄
                else:
                    state = "loading"   # ⚪ 加载中(不算售罄也不算可买)

                history.append(state)
                if len(history) > 5:
                    history.pop(0)

                # 触发条件:**最近 2 次都是 available**(避免首屏误判)
                recent_available = (
                    len(history) >= 2
                    and history[-1] == "available"
                    and history[-2] == "available"
                )

                status_icon = {"available": "🟢 可买", "sold_out": "🔴 售罄", "loading": "⚪ 加载"}[state]
                _print(f"#{attempt:4d} {elapsed:5d}s  {status_icon}  url={page.url[:40]}")

                if recent_available:
                    _print("🎉🎉🎉 检测到可买!连续 2 次确认。")
                    if args.on_available:
                        _print(f"执行回调: {args.on_available}")
                        try:
                            subprocess.Popen(args.on_available, shell=True)
                        except Exception as e:
                            _print(f"WARN: 回调执行失败: {e}")
                    break

                # 刷新 + 等智谱 SPA 套餐卡片加载完成
                await asyncio.sleep(interval)
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=10000)
                    # 等套餐卡片出现 —— 智谱 SPA 第一次 reload 时 body 是空的,第二次才填充
                    # 这里等至少 200 字符,绝对稳
                    for _ in range(20):  # 最多等 5 秒
                        body = await page.evaluate(
                            "() => document.body ? document.body.innerText.length : 0"
                        )
                        if body > 200:
                            break
                        await asyncio.sleep(0.25)
                except Exception as e:
                    _print(f"WARN: reload 失败: {e},继续探测")

        finally:
            await browser.close()

    return 0


def main():
    parser = argparse.ArgumentParser(description="持续探测 GLM Coding 套餐上架")
    parser.add_argument(
        "--interval", type=float, default=3.0,
        help="刷新间隔(秒),默认 3",
    )
    parser.add_argument(
        "--max-seconds", type=int, default=0,
        help="最大探测时长,0 = 无限,默认 0",
    )
    parser.add_argument(
        "--on-available", default="",
        help="检测到可买时执行的 shell 命令",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()