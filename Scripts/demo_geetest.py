
import asyncio
import os
from playwright.async_api import async_playwright
import time

async def main():
    output_dir = os.path.expanduser("~/.openclaw/workspaces/xiaoqian/tools/webauto/demo")
    os.makedirs(output_dir, exist_ok=True)

    print("=== 极验 Demo 测试 ===\n")
    print("注意：这是一个技术验证脚本，使用公开 demo 页面\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # 访问极验 demo 页面
        print("1. 访问极验 demo 页面...")
        await page.goto("https://www.geetest.com/demo/", wait_until="networkidle")
        await asyncio.sleep(2)

        demo_screenshot = os.path.join(output_dir, "geetest_demo_home.png")
        await page.screenshot(path=demo_screenshot)
        print(f"   首页截图: {demo_screenshot}")

        print("\n2. 页面已打开，请手动操作查看验证码样式")
        print("   - 尝试点击不同的验证码类型")
        print("   - 观察文字点选验证码")
        print("\n3. 按 Ctrl+C 结束，或关闭浏览器")

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n\n正在关闭浏览器...")

        await browser.close()
        print("Demo 完成")

if __name__ == "__main__":
    asyncio.run(main())
