
import asyncio
from playwright.async_api import async_playwright
import os

async def main():
    # 确保输出目录存在
    output_dir = os.path.expanduser("~/.openclaw/workspaces/xiaoqian/tools/webauto/research")
    os.makedirs(output_dir, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        print("正在访问智谱 AI 首页...")
        await page.goto("https://bigmodel.cn/", wait_until="networkidle")

        # 截图首页
        home_screenshot = os.path.join(output_dir, "zhipu_home.png")
        await page.screenshot(path=home_screenshot, full_page=True)
        print(f"首页截图已保存: {home_screenshot}")

        # 尝试找登录或购买套餐的按钮
        print("\n页面内容:")
        print(await page.title())

        # 保存 HTML 用于分析
        html_path = os.path.join(output_dir, "zhipu_home.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(await page.content())
        print(f"HTML 已保存: {html_path}")

        print("\n按 Enter 键关闭浏览器...")
        input()

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
