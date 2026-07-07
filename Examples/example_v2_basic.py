"""
WebAuto v2.0 基础用法示例
展示四种运行模式 + 智能选择器 + 链式调用

运行前确保:
  pip install -r requirements.txt
  python -m playwright install chromium   # 仅 browser/stealth/human 模式需要
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.WebAuto_v2 import (
    WebAuto,
    WebAutoConfig,
    WebAutoHttp,
    WebAutoStealth,
    WebAutoBrowser,
    WebAutoHuman,
)


async def demo_http_mode():
    """HTTP 模式:最快,纯请求"""
    print("\n=== Demo: HTTP Mode (Fastest) ===")
    async with WebAutoHttp(enable_time_sync=False) as auto:
        response = await auto.goto("https://example.com")
        print(f"Status: {response.status}")
        title = await auto.extract("h1")
        print(f"Title: {title}")


async def demo_stealth_mode():
    """隐形模式:绕过 90% 反爬"""
    print("\n=== Demo: Stealth Mode ===")
    async with WebAutoStealth(headless=True, enable_time_sync=False) as auto:
        await auto.goto("https://example.com")
        title = await auto.extract("h1")
        print(f"Title (stealth): {title}")


async def demo_browser_mode():
    """浏览器模式:交互场景"""
    print("\n=== Demo: Browser Mode ===")
    async with WebAutoBrowser(enable_time_sync=False) as auto:
        await auto.goto("https://example.com")
        title = await auto.extract("h1")
        print(f"Title (browser): {title}")
        # 演示按文本查找
        try:
            await auto.find_by_text("More information").click()
            print("Clicked link by text")
        except Exception as e:
            print(f"(skipped click test: {type(e).__name__})")


async def demo_smart_selector():
    """智能选择器:重试 + 超时 + fallback + adaptive"""
    print("\n=== Demo: Smart Selector ===")
    async with WebAutoHttp(enable_time_sync=False) as auto:
        await auto.goto("https://example.com")
        # 1. 多选择器 fallback
        title = await auto.find(
            ['h1', '#title', '.header'],  # 依次尝试
        ).retry(3).timeout(5000).text()
        print(f"Found via fallback: {title}")
        # 2. exists() 不抛异常
        exists = await auto.find('a').exists()
        print(f"<a> exists: {exists}")


async def demo_switch_modes():
    """四种模式自由切换,API 完全一致"""
    print("\n=== Demo: Mode Switching (Same API) ===")
    modes = ['http']  # 只跑 http 模式 (其他需要 chromium)
    for mode in modes:
        print(f"\nTesting mode: {mode}")
        config = WebAutoConfig(
            mode=mode,
            headless=True,
            enable_time_sync=False,
        )
        async with WebAuto(config) as auto:
            response = await auto.goto("https://example.com")
            title = await auto.extract("h1")
            print(f"  {mode}: status={response.status} title={title}")


async def main():
    print("WebAuto v2.0 Demo Suite")
    print("=" * 50)

    await demo_http_mode()
    # 以下 demo 需要 chromium, 在沙箱里跑会失败;注释掉
    # await demo_stealth_mode()
    # await demo_browser_mode()
    await demo_smart_selector()
    await demo_switch_modes()

    print("\nAll demos completed!")


if __name__ == "__main__":
    asyncio.run(main())